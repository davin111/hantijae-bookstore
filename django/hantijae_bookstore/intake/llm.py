"""ai-sidecar /complete 호출. 항상 단발 호출(history 없음)."""
import base64
import json
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

import requests


class LLMError(Exception):
    pass


class LLMAuthError(LLMError):
    """401/403 — 사이드카 토큰 또는 구독 OAuth 토큰 문제. 재시도 무의미."""


class LLMTransientError(LLMError):
    """429/5xx/네트워크 — 재시도."""


class LLMInvalidJSON(LLMError):
    pass


@dataclass
class Attachment:
    kind: str          # 'pdf' | 'image'
    media_type: str    # 'application/pdf' | 'image/jpeg' | 'image/png'
    data: bytes
    name: str = ''


class LLMClient(Protocol):
    def complete(self, system: str, user: str, attachments: Sequence[Attachment] = ()) -> str: ...


class SidecarClient:
    def __init__(self, url: str, token: str, model: str, timeout: int = 300, session=None):
        self.url = url.rstrip('/')
        self.token = token
        self.model = model
        self.timeout = timeout
        self.session = session or requests.Session()

    def complete(self, system, user, attachments=()):
        body = {
            'systemPrompt': system,
            'userMessage': user,
            'model': self.model,
            'attachments': [{'kind': a.kind, 'mediaType': a.media_type,
                             'data': base64.b64encode(a.data).decode(), 'name': a.name} for a in attachments],
        }
        try:
            res = self.session.post(f'{self.url}/complete', json=body, timeout=self.timeout,
                                    headers={'Authorization': f'Bearer {self.token}'})
        except requests.RequestException as e:
            raise LLMTransientError(f'network: {e}') from e
        if res.status_code == 200:
            return res.json().get('text', '')
        try:
            detail = res.json()
        except ValueError:
            detail = {}
        message = f"{res.status_code} {detail.get('error', '')} {detail.get('message', '')}".strip()
        if res.status_code in (401, 403):
            raise LLMAuthError(message)
        if res.status_code == 429 or res.status_code >= 500:
            raise LLMTransientError(message)
        raise LLMError(message)


def complete_with_retry(client, system, user, attachments=(), attempts=3, sleep=time.sleep):
    for i in range(attempts):
        try:
            return client.complete(system, user, attachments)
        except LLMTransientError:
            if i == attempts - 1:
                raise
            sleep((5, 20, 60)[min(i, 2)])


def parse_json_object(text: str) -> dict:
    """코드펜스·앞뒤 설명문이 섞여도 첫 번째 완결 JSON 객체를 찾는다."""
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == '{':
            try:
                obj, _ = decoder.raw_decode(text[i:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    raise LLMInvalidJSON(text[:200])


JSON_REMINDER = '\n\n반드시 JSON 객체 하나만 출력하세요. 설명 문장이나 코드펜스는 쓰지 마세요.'


def complete_json(client, system, user, attachments=(), sleep=time.sleep) -> dict:
    text = complete_with_retry(client, system, user, attachments, sleep=sleep)
    try:
        return parse_json_object(text)
    except LLMInvalidJSON:
        text = complete_with_retry(client, system, user + JSON_REMINDER, attachments, sleep=sleep)
        return parse_json_object(text)
