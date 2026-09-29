"""한티재 공식 페북 페이지·인스타의 최근 글(읽기 전용). 운영진 개인 글이 공식 채널에도 올라갔는지 볼 때 쓴다.
앱 설정 '앱 시크릿 코드 요청'이 켜져 있어 모든 호출에 appsecret_proof가 필요하다(없으면 code 100).
채널마다 따로 실패할 수 있다(인스타 데이터 접근 만료 2026-12-28) → 못 읽은 채널은 None('모름')."""
import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime

import requests
from django.conf import settings

from marketing.social_parse import parse_time

log = logging.getLogger('intake')
GRAPH = 'https://graph.facebook.com/v26.0'


@dataclass(frozen=True)
class OfficialPost:
    channel: str
    posted_at: datetime
    text: str
    url: str


def proof(token, secret):
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def _rows(get, path, params, cfg):
    token = cfg['META_PAGE_TOKEN']
    res = get(f'{GRAPH}/{path}', params={**params, 'access_token': token,
                                         'appsecret_proof': proof(token, cfg['META_APP_SECRET'])}, timeout=20)
    res.raise_for_status()
    return res.json().get('data', [])


def official_posts(since, get=requests.get):
    """{'facebook': [OfficialPost]|None, 'instagram': [...]|None} — since 이후 글만."""
    cfg = getattr(settings, 'MARKETING', {})
    out = {'facebook': None, 'instagram': None}
    if not (cfg.get('META_PAGE_TOKEN') and cfg.get('META_APP_SECRET')):
        return out
    if cfg.get('META_PAGE_ID'):
        try:
            rows = _rows(get, f'{cfg["META_PAGE_ID"]}/posts', {'fields': 'message,created_time,permalink_url',
                                                               'since': int(since.timestamp()), 'limit': 50}, cfg)
            out['facebook'] = [OfficialPost('facebook', parse_time(r.get('created_time')), r.get('message') or '',
                                            r.get('permalink_url') or '') for r in rows if parse_time(r.get('created_time'))]
        except Exception as e:  # 한 채널 실패는 '모름'으로 두고 넘어간다
            log.warning('meta facebook posts: %s', e)
    if cfg.get('META_IG_USER_ID'):
        try:
            rows = _rows(get, f'{cfg["META_IG_USER_ID"]}/media', {'fields': 'caption,timestamp,permalink', 'limit': 50},
                         cfg)
            posts = [OfficialPost('instagram', parse_time(r.get('timestamp')), r.get('caption') or '',
                                  r.get('permalink') or '') for r in rows if parse_time(r.get('timestamp'))]
            out['instagram'] = [p for p in posts if p.posted_at >= since]
        except Exception as e:
            log.warning('meta instagram media: %s', e)
    return out
