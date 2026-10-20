"""기존 sidecar의 SSE 응답을 읽는다. 완결된 응답만 사용하고 부분 그림은 버린다."""
import json
import time

import requests

from intake.llm import LLMAuthError, LLMError, LLMTransientError, SidecarClient


class VisualClient(SidecarClient):
    def review(self, system, user, attachments):
        """완성된 픽셀 검토는 도구 없는 첨부 API로 별도 요청한다."""
        return SidecarClient.complete(self, system, user, attachments)

    def complete(self, system, user, attachments=()):
        if attachments:
            raise ValueError('그림 코드는 파일 첨부 없이 요청합니다')
        body = {'systemPrompt': system, 'userMessage': user, 'model': self.model}
        # history를 넣으면 면접 전용 프롬프트가 붙으므로 항상 단발 요청이다.
        started = time.monotonic()
        text, event = '', ''
        try:
            with self.session.post(self.url + '/chat', json=body, stream=True,
                                   timeout=(15, self.timeout),
                                   headers={'Authorization': 'Bearer ' + self.token}) as response:
                if response.status_code in (401, 403):
                    raise LLMAuthError('sidecar 인증 확인 필요')
                if response.status_code != 200:
                    raise LLMTransientError('sidecar HTTP ' + str(response.status_code))
                for line in response.iter_lines(chunk_size=1024):
                    if time.monotonic() - started > self.timeout:
                        raise LLMTransientError('그림 응답 시간 초과')
                    if line.startswith(b'event: '):
                        event = line[7:].decode('ascii')
                    elif line.startswith(b'data: '):
                        value = json.loads(line[6:])
                        if event == 'delta' and isinstance(value, str):
                            text += value
                            if len(text.encode()) > 100_000:
                                raise LLMError('그림 응답 크기 초과')
                        elif event == 'done' and text:
                            return text
                        elif event == 'error':
                            raise LLMTransientError('sidecar 생성 실패')
        except (requests.RequestException, ValueError, UnicodeError) as exc:
            raise LLMTransientError('sidecar 응답 확인 실패') from exc
        raise LLMTransientError('sidecar 응답 미완료')
