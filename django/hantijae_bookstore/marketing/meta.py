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
    id: str = ''  # 반응 수를 다시 읽을 때 쓰는 글 번호


def proof(token, secret):
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


class MetaError(Exception):
    """주소(토큰이 들어 있음)를 담지 않은 오류. requests의 오류 문구는 주소를 그대로 담으므로 쓰지 않는다."""


def _rows(get, path, params, cfg):
    token = cfg['META_PAGE_TOKEN']
    try:
        res = get(f'{GRAPH}/{path}', params={**params, 'access_token': token,
                                             'appsecret_proof': proof(token, cfg['META_APP_SECRET'])}, timeout=20)
    except requests.RequestException as e:
        raise MetaError(type(e).__name__) from None
    if res.status_code >= 400:
        raise MetaError(f'HTTP {res.status_code}')
    return res.json().get('data', [])


def official_posts(since, get=requests.get):
    """{'facebook': [OfficialPost]|None, 'instagram': [...]|None} — since 이후 글만."""
    cfg = getattr(settings, 'MARKETING', {})
    out = {'facebook': None, 'instagram': None}
    if not (cfg.get('META_PAGE_TOKEN') and cfg.get('META_APP_SECRET')):
        return out
    if cfg.get('META_PAGE_ID'):
        try:
            rows = _rows(get, f'{cfg["META_PAGE_ID"]}/posts', {'fields': 'id,message,created_time,permalink_url',
                                                               'since': int(since.timestamp()), 'limit': 50}, cfg)
            out['facebook'] = [OfficialPost('facebook', parse_time(r.get('created_time')), r.get('message') or '',
                                            r.get('permalink_url') or '', str(r.get('id') or ''))
                               for r in rows if parse_time(r.get('created_time'))]
        except Exception as e:  # 한 채널 실패는 '모름'으로 두고 넘어간다(로그에는 종류·상태 코드만)
            log.warning('meta facebook posts: %s', e if isinstance(e, MetaError) else type(e).__name__)
    if cfg.get('META_IG_USER_ID'):
        try:
            rows = _rows(get, f'{cfg["META_IG_USER_ID"]}/media', {'fields': 'id,caption,timestamp,permalink', 'limit': 50},
                         cfg)
            posts = [OfficialPost('instagram', parse_time(r.get('timestamp')), r.get('caption') or '',
                                  r.get('permalink') or '', str(r.get('id') or '')) for r in rows if parse_time(r.get('timestamp'))]
            out['instagram'] = [p for p in posts if p.posted_at >= since]
        except Exception as e:
            log.warning('meta instagram media: %s', e if isinstance(e, MetaError) else type(e).__name__)
    return out


COUNT_FIELDS = {'facebook': 'reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0),shares',
                'instagram': 'like_count,comments_count'}


def post_counts(channel, post_id, get=requests.get):
    """공식 글 하나의 반응 수. 페북 {'reactions','comments','shares'}, 인스타 {'likes','comments'}. 못 읽으면 None."""
    cfg = getattr(settings, 'MARKETING', {})
    if not (post_id and channel in COUNT_FIELDS and cfg.get('META_PAGE_TOKEN') and cfg.get('META_APP_SECRET')):
        return None
    token = cfg['META_PAGE_TOKEN']
    try:
        res = get(f'{GRAPH}/{post_id}', params={'fields': COUNT_FIELDS[channel], 'access_token': token,
                                               'appsecret_proof': proof(token, cfg['META_APP_SECRET'])}, timeout=20)
        if res.status_code >= 400:
            raise MetaError(f'HTTP {res.status_code}')
        d = res.json()
        if channel == 'facebook':
            return {'reactions': int(((d.get('reactions') or {}).get('summary') or {}).get('total_count') or 0),
                    'comments': int(((d.get('comments') or {}).get('summary') or {}).get('total_count') or 0),
                    'shares': int((d.get('shares') or {}).get('count') or 0)}
        return {'likes': int(d.get('like_count') or 0), 'comments': int(d.get('comments_count') or 0)}
    except Exception as e:  # 주소(토큰)는 로그에 남기지 않는다
        log.warning('meta %s counts: %s', channel, e if isinstance(e, MetaError) else type(e).__name__)
        return None
