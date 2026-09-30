"""한티재 공식 페북 페이지·인스타의 최근 글(읽기 전용). 운영진 개인 글이 공식 채널에도 올라갔는지 볼 때 쓴다.
앱 설정 '앱 시크릿 코드 요청'이 켜져 있어 모든 호출에 appsecret_proof가 필요하다(없으면 code 100).
채널마다 따로 실패할 수 있다(인스타 데이터 접근 만료 2026-12-28) → 못 읽은 채널은 None('모름')."""
import hashlib
import hmac
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

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
    """주소(토큰이 들어 있음)를 담지 않은 오류. requests의 오류 문구는 주소를 그대로 담으므로 쓰지 않는다.
    code는 Graph API의 error.code(있을 때)."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class MetaAuthError(MetaError):
    """토큰 만료·권한 문제. 다시 발급해야 풀린다(런북 .claude/docs/meta-api/2026-09-29/00-overview.md)."""


AUTH_CODES = {190, 102, 10, 200}
TOKEN_CODES = {190, 102}   # 토큰 만료·세션 문제 — 계정별 호출에서도 이때만 그대로 올린다(10·200은 그 계정만의 문제로 본다)
NOT_BUSINESS = 110   # business_discovery: 개인 계정이거나 없는 아이디(subcode 2207013)
TAGS_PAGE, TAGS_PAGES = 10, 5   # /tags는 한 번에 10개 넘게 물으면 code 1로 거절한다
_USERNAME = re.compile(r'^[A-Za-z0-9._]{1,30}$')


def _call(get, path, params, cfg):
    token = cfg['META_PAGE_TOKEN']
    try:
        res = get(f'{GRAPH}/{path}', params={**params, 'access_token': token,
                                             'appsecret_proof': proof(token, cfg['META_APP_SECRET'])}, timeout=20)
    except requests.RequestException as e:
        raise MetaError(type(e).__name__) from None
    if res.status_code >= 400:
        try:
            code = ((res.json() or {}).get('error') or {}).get('code')
        except ValueError:
            code = None
        cls = MetaAuthError if code in AUTH_CODES else MetaError
        raise cls(f'HTTP {res.status_code}' + (f' code {code}' if code else ''), code)
    try:
        data = res.json()
    except ValueError:
        raise MetaError(f'HTTP {res.status_code} not JSON') from None
    if not isinstance(data, dict):
        raise MetaError(f'HTTP {res.status_code} unexpected body')
    return data


def _rows(get, path, params, cfg):
    return _call(get, path, params, cfg).get('data', [])


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


@dataclass(frozen=True)
class Media:
    """인스타 글 하나(한티재를 태그한 글·다른 계정의 글). username은 태그 글에만 채운다(글쓴 계정)."""
    id: str
    caption: str
    url: str
    posted_at: datetime
    username: str = ''
    likes: int = 0
    comments: int = 0


def _ig_config():
    cfg = getattr(settings, 'MARKETING', {})
    return cfg if cfg.get('META_PAGE_TOKEN') and cfg.get('META_APP_SECRET') and cfg.get('META_IG_USER_ID') else None


def ig_configured():
    return _ig_config() is not None


def _media(rows, with_username=False):
    out = []
    for r in rows:
        at = parse_time(r.get('timestamp'))
        if at and r.get('permalink'):
            out.append(Media(str(r.get('id') or ''), r.get('caption') or '', r['permalink'], at,
                             (r.get('username') or '') if with_username else '',
                             int(r.get('like_count') or 0), int(r.get('comments_count') or 0)))
    return out


def tagged_media(get=requests.get):
    """한티재 인스타를 태그한 공개 글(최근 것부터), 최대 TAGS_PAGES쪽을 TAGS_PAGE개씩(더 크게 물으면 Graph가 거절한다).
    설정이 없으면 []. 첫 쪽이 실패하면 올린다(권한 문제는 어느 쪽이든 올린다). 다음 쪽이 실패하면 그때까지 읽은 것을 돌려준다.
    next 주소는 부르지 않는다(토큰이 들어 있다) — 대신 cursors.after로 다음 쪽을 요청한다."""
    cfg = _ig_config()
    if not cfg:
        return []
    fields = 'id,caption,permalink,timestamp,username,like_count,comments_count'
    rows, after = [], None
    for page in range(1, TAGS_PAGES + 1):
        params = {'fields': fields, 'limit': TAGS_PAGE}
        if after:
            params['after'] = after
        try:
            data = _call(get, f'{cfg["META_IG_USER_ID"]}/tags', params, cfg)
        except MetaAuthError:
            raise
        except MetaError as e:
            if page == 1:
                raise
            log.warning('meta tags page %d stopped: %s', page, e)
            break
        rows.extend(data.get('data', []))
        paging = data.get('paging') or {}
        after = (paging.get('cursors') or {}).get('after')
        if not paging.get('next') or not after:
            break
    return _media(rows, with_username=True)


def business_media(username, limit=25, get=requests.get) -> Optional[List[Media]]:
    """프로페셔널 계정의 최근 글. 개인 계정·없는 아이디·아이디 모양이 아니면 None. 그 밖의 오류는 올린다."""
    cfg = _ig_config()
    if not cfg or not _USERNAME.match(username or ''):
        return None
    fields = (f'business_discovery.username({username})'
              f'{{media.limit({limit}){{id,caption,permalink,timestamp,like_count,comments_count}}}}')
    try:
        data = _call(get, cfg['META_IG_USER_ID'], {'fields': fields}, cfg)
    except MetaError as e:
        if e.code == NOT_BUSINESS:
            return None
        raise
    return _media(((data.get('business_discovery') or {}).get('media') or {}).get('data', []))


@dataclass(frozen=True)
class ChannelPost:
    channel: str
    posted_at: datetime
    text: str
    url: str
    reactions: int   # 페북 반응(좋아요 포함) · 인스타 좋아요
    comments: int
    shares: int = 0


def _count(d, name):
    return int(((d.get(name) or {}).get('summary') or {}).get('total_count') or 0)


def channel_posts(since, until, get=requests.get):
    """[since, until) 사이 공식 페북·인스타 글과 반응 수. 채널마다 한 번 부른다. 못 읽은 채널은 None."""
    cfg = getattr(settings, 'MARKETING', {})
    out = {'facebook': None, 'instagram': None}
    if not (cfg.get('META_PAGE_TOKEN') and cfg.get('META_APP_SECRET')):
        return out
    if cfg.get('META_PAGE_ID'):
        try:
            rows = _rows(get, f'{cfg["META_PAGE_ID"]}/posts',
                         {'fields': 'message,created_time,permalink_url,shares,reactions.summary(total_count).limit(0),'
                                    'comments.summary(total_count).limit(0)',
                          'since': int(since.timestamp()), 'until': int(until.timestamp()), 'limit': 50}, cfg)
            posts = []
            for r in rows:
                at = parse_time(r.get('created_time'))
                if at and since <= at < until:
                    posts.append(ChannelPost('facebook', at, r.get('message') or '', r.get('permalink_url') or '',
                                             _count(r, 'reactions'), _count(r, 'comments'),
                                             int((r.get('shares') or {}).get('count') or 0)))
            out['facebook'] = posts
        except Exception as e:  # 한 채널 실패는 '못 읽음'으로 두고 넘어간다(로그에는 종류·상태 코드만)
            log.warning('meta facebook week: %s', e if isinstance(e, MetaError) else type(e).__name__)
    if cfg.get('META_IG_USER_ID'):
        try:
            rows = _rows(get, f'{cfg["META_IG_USER_ID"]}/media',
                         {'fields': 'caption,timestamp,permalink,like_count,comments_count', 'limit': 50}, cfg)
            posts = []
            for r in rows:
                at = parse_time(r.get('timestamp'))
                if at and since <= at < until:
                    posts.append(ChannelPost('instagram', at, r.get('caption') or '', r.get('permalink') or '',
                                             int(r.get('like_count') or 0), int(r.get('comments_count') or 0)))
            out['instagram'] = posts
        except Exception as e:
            log.warning('meta instagram week: %s', e if isinstance(e, MetaError) else type(e).__name__)
    return out
