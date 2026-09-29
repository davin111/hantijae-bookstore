"""Apify 페북·인스타 결과를 공통 모양(Post)으로. 순수 함수(DB·네트워크 없음).
공유 글은 본인이 덧붙인 말(text)과 공유 원문(shared)을 따로 둔다 — 본인 말이 비어 있어도 원문에 내용이 있다.
원문 작성자·원문 날짜(shared)와 공유한 사람·공유 날짜(account·posted_at)를 섞지 않는다."""
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List

FACEBOOK, INSTAGRAM = 'facebook', 'instagram'


@dataclass
class Post:
    platform: str
    account: str  # 역할 키
    post_id: str
    url: str
    posted_at: datetime
    text: str = ''
    shared: dict = field(default_factory=dict)
    link: dict = field(default_factory=dict)

    def full_text(self):
        return '\n'.join(t for t in (self.text, self.shared.get('text', ''), self.link.get('title', '')) if t)


@dataclass
class Parsed:
    posts: List[Post]
    counts: Dict[str, dict]  # 역할 키 → {items, valid, errors}
    unknown: int = 0         # 어느 계정인지 모르는 항목


def parse_time(value):
    """'2026-09-29T02:35:04.000Z'·'2026-09-18T09:10:34+0000'·유닉스 초 → UTC 기준 datetime. 못 읽으면 None."""
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    text = str(value).strip().replace('Z', '+00:00')
    if len(text) > 5 and text[-5] in '+-' and text[-4:].isdigit():  # +0000 → +00:00
        text = text[:-2] + ':' + text[-2:]
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fb_key(url):
    """페북 프로필 주소 → 비교 열쇠(호스트·끝 빗금·대소문자 무시)."""
    parts = urllib.parse.urlsplit((url or '').strip())
    key = parts.path.strip('/').lower()
    if key == 'profile.php':
        key += '?id=' + urllib.parse.parse_qs(parts.query).get('id', [''])[0]
    return key


def share_key(url):
    """공유 원문 주소 → 묶음 열쇠. 추적 인자와 www·m 차이를 없앤다(pfbid는 대소문자를 가리므로 그대로)."""
    parts = urllib.parse.urlsplit((url or '').strip())
    host = parts.netloc.lower()
    for prefix in ('www.', 'm.', 'web.'):
        host = host.removeprefix(prefix)
    return host + parts.path.rstrip('/')


def _counts(roles):
    return {r: {'items': 0, 'valid': 0, 'errors': 0} for r in roles}


def _fb_shared(sp):
    if not isinstance(sp, dict) or not (sp.get('url') or sp.get('text')):
        return {}
    when = parse_time(sp.get('time') or sp.get('timestamp'))
    page = sp.get('pageName')
    author = (sp.get('user') or {}).get('name') or (page.get('name') if isinstance(page, dict) else '') or ''
    return {'url': sp.get('url') or '', 'text': sp.get('text') or '', 'author': author,
            'posted_at': when.isoformat() if when else ''}


def _fb_link(it):
    url = it.get('link') or (it.get('previewTarget') or {}).get('external_url') or ''
    if not (url or it.get('previewTitle')):
        return {}
    return {'url': url, 'title': it.get('previewTitle') or '', 'source': it.get('previewSource') or ''}


def parse_facebook(items, accounts):
    roles = {fb_key(a['facebook']): a['role'] for a in accounts if a.get('facebook')}
    counts, posts, unknown = _counts(roles.values()), [], 0
    for it in items:
        src = it.get('inputUrl') or it.get('facebookUrl') or (it.get('url', '') if it.get('error') else '')
        role = roles.get(fb_key(src))
        if role is None:
            unknown += 1
            continue
        c = counts[role]
        c['items'] += 1
        if it.get('error'):
            c['errors'] += 1
            continue
        when = parse_time(it.get('time') or it.get('timestamp'))
        if not (it.get('postId') and it.get('url') and when):
            continue
        c['valid'] += 1
        posts.append(Post(FACEBOOK, role, str(it['postId']), it['url'], when, it.get('text') or '',
                          _fb_shared(it.get('sharedPost')), _fb_link(it)))
    return Parsed(posts, counts, unknown)


def _ig_owner(it):
    name = it.get('ownerUsername') or it.get('username') or ''
    if not name and it.get('error'):
        name = urllib.parse.urlsplit(it.get('inputUrl') or it.get('url') or '').path.strip('/').split('/')[0]
    return str(name).strip().lstrip('@').lower()


def parse_instagram(items, accounts):
    roles = {a['instagram'].strip().lstrip('@').lower(): a['role'] for a in accounts if a.get('instagram')}
    counts, posts, unknown = _counts(roles.values()), [], 0
    for it in items:
        role = roles.get(_ig_owner(it))
        if role is None:
            unknown += 1
            continue
        c = counts[role]
        c['items'] += 1
        if it.get('error'):
            c['errors'] += 1
            continue
        when = parse_time(it.get('timestamp'))
        if not (it.get('id') and it.get('url') and when):
            continue
        c['valid'] += 1
        posts.append(Post(INSTAGRAM, role, str(it['id']), it['url'], when, it.get('caption') or ''))
    return Parsed(posts, counts, unknown)
