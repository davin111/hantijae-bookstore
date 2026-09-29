"""운영진 개인 SNS 글 해석: 묶기 → LLM 판정 → 책·날짜 확인 → Signal(kind=social).
LLM이 말한 책 제목·행사 날짜는 글에 실제로 있는지 코드로 다시 확인한다(지어낸 것 거르기)."""
import hashlib
import re
from datetime import date, timedelta

from books.models import Book
from intake.llm import complete_json
from marketing.models import Signal, SocialPost
from marketing.prompts import SOCIAL_JUDGE_SYSTEM, build_social_user
from marketing.social_parse import share_key
from marketing.text import loose_key, similarity
from marketing.timeutil import kst_today

SAME_POST_RATIO, SAME_POST_WINDOW, MIN_TEXT = 0.85, timedelta(days=3), 20
PER_CALL, JUDGE_DAYS, SAME_EVENT_DAYS, SAME_EVENT_NAME, LINK_LATER_DAYS = 15, 30, 30, 0.6, 60
CATEGORIES = ('new_book', 'event', 'funding', 'review', 'press', 'author_news', 'other')
CATEGORY_LABEL = {'new_book': '신간', 'event': '행사', 'funding': '펀딩', 'review': '서평', 'press': '기사',
                  'author_news': '저자 소식', 'other': '소식'}
_SITE_BOOK = re.compile(r'hantijae-bookstore\.com/book=(\d+)')


def _long_enough(text):
    return len(re.sub(r'\s+', '', text or '')) >= MIN_TEXT


def _posts_at(key):
    """주소의 묶음 열쇠(share_key)가 key인 저장된 글."""
    base = key.split('?', 1)[0]
    path = base.split('/', 1)[1] if '/' in base else base
    return [p for p in SocialPost.objects.filter(url__contains=path).exclude(group_key='').order_by('first_seen', 'id')
            if share_key(p.url) == key]


def assign_group(post):
    """새 글의 묶음 열쇠. 같은 원문 공유(운영진끼리 서로의 글을 공유한 것 포함) → ±3일 안의 거의 같은 글
    (페북·인스타 복사) → 자기 자신. 공유와 원글 중 어느 쪽이 먼저 저장돼도 같은 묶음이 되게 양쪽에서 찾는다."""
    if post.shared.get('url'):
        key = share_key(post.shared['url'])
        original = [p for p in _posts_at(key) if p.pk != post.pk]
        return original[0].group_key if original else 'share:' + key
    shared_me = SocialPost.objects.filter(group_key='share:' + share_key(post.url)).exclude(pk=post.pk)
    if shared_me.exists():
        return 'share:' + share_key(post.url)
    if _long_enough(post.text):
        near = (SocialPost.objects.filter(posted_at__gte=post.posted_at - SAME_POST_WINDOW,
                                          posted_at__lte=post.posted_at + SAME_POST_WINDOW)
                .exclude(pk=post.pk).exclude(group_key='').order_by('first_seen', 'id'))
        for other in near:
            if _long_enough(other.text) and similarity(post.text, other.text) >= SAME_POST_RATIO:
                return other.group_key
    return f'post:{post.platform}:{post.post_id}'


# ---- 책 목록 ----

def catalog_keys():
    """(비교 열쇠, 책). 공개된 책만."""
    return [(loose_key(b.title), b) for b in Book.objects.filter(is_published=True) if len(loose_key(b.title)) >= 2]


def catalog_lines():
    books = Book.objects.filter(is_published=True).prefetch_related('authors__author').order_by('-published_date')
    return [f'{b.title} | {b.subtitle or ""} | {", ".join(ba.author.name for ba in b.authors.all())}' for b in books]


def match_title(key, keys):
    """글에 적힌 제목 열쇠 → 책. 똑같은 것 먼저, 없으면 4자 이상 포함 관계 가운데 가장 긴 책 제목."""
    for k, b in keys:
        if k == key:
            return b
    near = [(len(k), b) for k, b in keys if len(k) >= 4 and len(key) >= 4 and (k in key or key in k)]
    return max(near, key=lambda x: x[0])[1] if near else None


# ---- LLM 판정 확인 ----

def mentions_day(text, day):
    """글에 그 달·날이 적혀 있나('10월 12일', '10/12', '10.12')."""
    m, d = day.month, day.day
    return any(re.search(p, text or '') for p in (rf'(?<!\d)0?{m}\s*월\s*0?{d}\s*일', rf'(?<!\d)0?{m}\s*[./]\s*0?{d}(?!\d)'))


def check_event(raw, post):
    """LLM이 말한 행사. 날짜는 게시일 -7일~+120일이고 글에 그 달·날이 있을 때만 믿는다."""
    if not isinstance(raw, dict):
        return None
    name, place = str(raw.get('name') or '').strip()[:100], str(raw.get('place') or '').strip()[:100]
    try:
        on = date.fromisoformat(str(raw.get('date') or ''))
    except ValueError:
        on = None
    posted = kst_today(post.posted_at)
    if on and not (posted - timedelta(days=7) <= on <= posted + timedelta(days=120)
                   and mentions_day(post.full_text(), on)):
        on = None
    if not (on or name):
        return None
    return {'on': on.isoformat() if on else '', 'name': name, 'place': place}


def clean_verdict(raw, post, keys):
    text = post.full_text()
    hay = loose_key(text)
    books, titles = [], []
    for t in raw.get('books') or []:
        k = loose_key(str(t))
        if len(k) < 2 or k not in hay:  # 글에 없는 제목(지어낸 것)은 버린다
            continue
        b = match_title(k, keys)
        if b and b.id not in books:
            books.append(b.id)
        elif not b and str(t).strip()[:100] not in titles:
            titles.append(str(t).strip()[:100])
    for m in _SITE_BOOK.finditer(' '.join([text, post.link.get('url', '')])):
        bid = int(m.group(1))
        if bid not in books and Book.objects.filter(pk=bid, is_published=True).exists():
            books.append(bid)
    return {'relevant': bool(raw.get('relevant')), 'private': bool(raw.get('private')),
            'sensitive': bool(raw.get('sensitive')),
            'category': raw.get('category') if raw.get('category') in CATEGORIES else 'other',
            'books': books, 'titles': titles, 'event': check_event(raw.get('event'), post),
            'summary': str(raw.get('summary') or '').strip()[:300]}


# ---- 신호 ----

def _key(group_key):
    return 'social:' + hashlib.sha1(group_key.encode()).hexdigest()


def add_source(sig, post, role_labels):
    d = dict(sig.detail)
    for name, value in (('roles', post.account), ('who', role_labels.get(post.account, post.account)),
                        ('platforms', post.platform), ('urls', post.url), ('shared_urls', post.shared.get('url'))):
        if value and value not in d.get(name, []):
            d[name] = d.get(name, []) + [value]
    sig.detail = d
    sig.save(update_fields=['detail'])


SAME_SUBJECT = ('funding', 'new_book')  # 같은 책의 펀딩·출간 글은 여러 번 올라와도 사건 하나


def same_subject(v, now):
    """30일 안에 같은 사건의 신호가 있으면 그것: 날짜 있는 행사는 같은 날 + (같은 책 또는 비슷한 이름),
    펀딩·신간은 같은 분류 + (같은 책 또는 같은 미등록 제목)."""
    ev = v['event'] or {}
    recent = Signal.objects.filter(kind=Signal.SOCIAL, found_at__gte=now - timedelta(days=SAME_EVENT_DAYS))
    if ev.get('on'):
        for s in recent.filter(happens_on=date.fromisoformat(ev['on'])):
            other = s.detail.get('event') or {}
            if other.get('on') != ev['on']:  # 같은 날 올라온 행사 아닌 글(신간·서평)과는 합치지 않는다
                continue
            if set(s.detail.get('books') or []) & set(v['books']):
                return s
            if ev.get('name') and other.get('name') and similarity(ev['name'], other['name']) >= SAME_EVENT_NAME:
                return s
        return None
    if v['category'] in SAME_SUBJECT and (v['books'] or v['titles']):
        titles = {loose_key(t) for t in v['titles']}
        for s in recent.order_by('found_at', 'id'):
            if s.detail.get('category') != v['category'] or (s.detail.get('event') or {}).get('on'):
                continue
            if (set(s.detail.get('books') or []) & set(v['books'])
                    or titles & {loose_key(t) for t in s.detail.get('titles') or []}):
                return s
    return None


def _new_signal(post, v, role_labels):
    ev = v['event'] or {}
    posted = kst_today(post.posted_at)
    book = Book.objects.filter(pk=v['books'][0]).first() if v['books'] else None
    link = {k: post.link.get(k, '') for k in ('title', 'source', 'url')} if post.link else {}
    return Signal.objects.create(
        kind=Signal.SOCIAL, key=_key(post.group_key), book=book,
        title=f'{CATEGORY_LABEL[v["category"]]} ― {v["summary"] or CATEGORY_LABEL[v["category"]]}'[:500],
        url=post.url[:1000], happens_on=date.fromisoformat(ev['on']) if ev.get('on') else posted,
        relevant=True, sensitive=v['sensitive'],
        detail={'category': v['category'], 'summary': v['summary'], 'event': v['event'], 'books': v['books'],
                'titles': v['titles'], 'roles': [post.account], 'who': [role_labels.get(post.account, post.account)],
                'platforms': [post.platform], 'urls': [post.url],
                'shared_urls': [post.shared['url']] if post.shared.get('url') else [], 'link': link,
                'posted_on': posted.isoformat()})


def attach(post, v, now, role_labels):
    """관련 글을 신호에 잇는다: 같은 사건 신호 → 같은 묶음 신호 → 새 신호."""
    sig = same_subject(v, now) or Signal.objects.filter(key=_key(post.group_key)).first()
    if sig:
        add_source(sig, post, role_labels)
    else:
        sig = _new_signal(post, v, role_labels)
    post.signal = sig
    post.save(update_fields=['signal'])
    return sig


def _follow(post, rep, now, role_labels):
    """같은 묶음의 대표 판정을 따른다(LLM을 다시 부르지 않음)."""
    post.verdict, post.judged_at, post.signal = {'follows': rep.id}, now, rep.signal
    post.save(update_fields=['verdict', 'judged_at', 'signal'])
    if rep.signal:
        add_source(rep.signal, post, role_labels)
        return [rep.signal]
    return []


def judge_pending(llm, now, role_labels):
    """판정 안 된 최근 글을 묶음마다 대표 하나씩 LLM에 보낸다. 만들었거나 붙은 신호 목록.
    LLM이 빠뜨린 글은 판정하지 않은 채 두어 다음에 다시 본다."""
    pending = list(SocialPost.objects.filter(judged_at__isnull=True, posted_at__gte=now - timedelta(days=JUDGE_DAYS))
                   .order_by('first_seen', 'id'))
    touched, reps = [], {}
    for p in pending:
        judged = (SocialPost.objects.filter(group_key=p.group_key, judged_at__isnull=False)
                  .exclude(pk=p.pk).order_by('first_seen', 'id'))
        rep = next((j for j in judged if not j.verdict.get('baseline')), None)  # 기준선 글은 판정한 게 아니다
        if rep:
            touched += _follow(p, rep, now, role_labels)
        elif p.group_key not in reps:
            reps[p.group_key] = p
    order = list(reps.values())
    if order:
        keys, lines = catalog_keys(), catalog_lines()
    for start in range(0, len(order), PER_CALL):
        chunk = order[start:start + PER_CALL]
        out = complete_json(llm, SOCIAL_JUDGE_SYSTEM, build_social_user(chunk, lines, role_labels))
        by_id = {v.get('id'): v for v in out.get('items', []) if isinstance(v, dict)}
        for i, p in enumerate(chunk):
            if i not in by_id:
                continue
            v = clean_verdict(by_id[i], p, keys)
            p.verdict, p.judged_at = v, now
            p.save(update_fields=['verdict', 'judged_at'])
            if v['relevant'] and not v['private']:
                touched.append(attach(p, v, now, role_labels))
    for p in pending:
        rep = reps.get(p.group_key)
        if p.judged_at is None and rep is not None and rep is not p and rep.judged_at is not None:
            touched += _follow(p, rep, now, role_labels)
    return touched


def link_later(now):
    """책 없이 만든 신호를 새로 등록된 책과 잇는다. 이은 신호 수."""
    keys, linked = catalog_keys(), 0
    for s in Signal.objects.filter(kind=Signal.SOCIAL, book__isnull=True,
                                   found_at__gte=now - timedelta(days=LINK_LATER_DAYS)):
        found, left = [], []
        for t in s.detail.get('titles') or []:
            b = match_title(loose_key(t), keys)
            (found if b else left).append(b or t)
        if found:
            s.book = found[0]
            s.detail = {**s.detail, 'books': (s.detail.get('books') or []) + [b.id for b in found], 'titles': left}
            s.save(update_fields=['book', 'detail'])
            linked += 1
    return linked
