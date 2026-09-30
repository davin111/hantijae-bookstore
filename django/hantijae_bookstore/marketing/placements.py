"""[올렸어요]를 누른 초안이 실제로 어디에 올라갔는지 찾는다(2026-09-30).

왜: 버튼은 초안 종류(인스타 글)만 알아서, 인스타 초안을 페북에 올려도 2주 뒤 성과 문구가 '인스타 글'이라고 했다.
운영진에게 어디에 올렸는지 묻지 않고(버튼·명령을 더 늘리지 않음), 봇이 이미 읽는 곳과 견준다:
한티재 페북 페이지·인스타(Meta API), 운영진 개인 계정(SocialPost), 블로그(RSS).
같은 글인지: 책 제목이 들어 있거나 초안과 50% 넘게 같으면, 누른 때 2일 전 ~ 3일 뒤 글.
매일 한 번(tasks, 12:00 — 개인 계정 수집 06:20 뒤) 최근 7일에 누른 초안만 본다. 찾은 곳은 Draft.placements에 쌓는다.
"""
from datetime import timedelta

from marketing import meta
from marketing.models import Draft, SocialPost
from marketing.text import loose_key, similarity
from marketing.timeutil import KST

LOOK_DAYS, BEFORE_DAYS, AFTER_DAYS, SAME_TEXT = 7, 2, 3, 0.5
OFFICIAL_LABEL = {'facebook': '한티재 페북 페이지', 'instagram': '한티재 인스타'}
PLATFORM_KO = {'facebook': '페이스북', 'instagram': '인스타그램'}


def _window(draft):
    return draft.posted_at - timedelta(days=BEFORE_DAYS), draft.posted_at + timedelta(days=AFTER_DAYS)


def _same(text, draft, key):
    return bool(text) and ((len(key) >= 4 and key in loose_key(text)) or similarity(text, draft.body) >= SAME_TEXT)


def find(draft, official, social_posts, blog_posts, labels):
    """이 초안이 올라간 곳 목록. official: {'facebook': [OfficialPost]|None, ...}(None = 못 읽음)."""
    start, end = _window(draft)
    key = loose_key(draft.proposal.book.title)
    out = []
    for kind in ('facebook', 'instagram'):
        for p in official.get(kind) or []:
            if start <= p.posted_at <= end and _same(p.text, draft, key):
                out.append({'kind': kind, 'label': OFFICIAL_LABEL[kind], 'url': p.url, 'id': p.id,
                            'at': p.posted_at.isoformat()})
    for s in social_posts:
        if start <= s.posted_at <= end and not s.text_cleared_at and _same(s.full_text(), draft, key):
            who = f'{labels[s.account]}님' if s.account in labels else '운영진'
            out.append({'kind': 'personal', 'label': f'{who} {PLATFORM_KO.get(s.platform, s.platform)}', 'url': s.url,
                        'at': s.posted_at.isoformat()})
    first, last = start.astimezone(KST).date(), end.astimezone(KST).date()
    for b in blog_posts or []:
        if b.date and first <= b.date <= last and len(key) >= 4 and key in loose_key(b.title):
            out.append({'kind': 'blog', 'label': '네이버 블로그', 'url': b.url, 'at': b.date.isoformat()})
    return out


def _merge(old, new):
    seen = {(p.get('kind'), p.get('url')) for p in old}
    return list(old) + [p for p in new if (p['kind'], p['url']) not in seen]


def update_recent(now, official_posts=meta.official_posts, blog_posts=lambda: None, labels=None):
    """최근 7일에 [올렸어요]를 누른 초안마다 올라간 곳을 찾아 쌓는다. 새로 찾은 초안 수를 돌려준다.
    그런 초안이 없으면 아무 곳도 읽지 않는다."""
    drafts = list(Draft.objects.filter(status=Draft.POSTED, posted_at__gte=now - timedelta(days=LOOK_DAYS),
                                       proposal__book__isnull=False).select_related('proposal__book'))
    if not drafts:
        return 0
    since = min(d.posted_at for d in drafts) - timedelta(days=BEFORE_DAYS)
    official = official_posts(since)
    social_posts = list(SocialPost.objects.filter(posted_at__gte=since, text_cleared_at__isnull=True))
    blog = blog_posts()
    changed = 0
    for d in drafts:
        merged = _merge(d.placements or [], find(d, official, social_posts, blog, labels or {}))
        if merged != (d.placements or []):
            Draft.objects.filter(pk=d.pk).update(placements=merged)
            changed += 1
    return changed
