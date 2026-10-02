"""월간 돌아보기(매달 3일 09:30, 검수 방). 스펙 .claude/docs/specs/2026-10-02-monthly-review-design.md(로컬).
자료와 출처는 코드가 모은다. LLM은 있었던 일을 추리고 올린 글 주제·제안만 쓴다(compose) — 출처는 코드가 근거 번호로 붙인다."""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

from django.db.models import Max, Sum

from books.models import Book
from intake.models import FundingCampaign, ReviewItem
from marketing import bnk_sales, meta
from marketing.candidates import sns_where
from marketing.funding import ends_on
from marketing.messages import _clock
from marketing.models import BnkSale, Draft, FundingSnapshot, GrantCall, HookDate, Signal
from marketing.timeutil import KST, kst_today
from web.blog import fetch_rss, parse_rss

log = logging.getLogger('intake')
TOP_BOOKS, MAX_EVENTS = 5, 10
PLATFORMS = (('facebook', '페이스북'), ('instagram', '인스타그램'))


@dataclass
class Item:
    """있었던 일 후보 하나. 번호·날짜·사실 한 줄·출처는 코드가 만든다."""
    no: int
    day: Optional[date]
    text: str
    source: str


def month_end(start):
    return bnk_sales._month_end(start)


def _book_name(title):
    """'농부, 짠한 형 - 두물머리 …'처럼 부제가 붙은 펀딩 제목에서 책 제목만."""
    return (title or '').split(' - ')[0].strip()


# ---- 판매 ----

def _weeks(start, end):
    out, day = [], start
    while day <= end:
        last = min(day + timedelta(days=6), end)
        n = BnkSale.objects.filter(day__range=(day, last)).aggregate(t=Sum('total'))['t'] or 0
        out.append((f'{day.day}~{last.day}일', n))
        day = last + timedelta(days=1)
    return out


def sales(start, end, client):
    """지난달 판매(전산망). 판매 경로·구매자는 그때 사이트에서 읽고, 못 읽으면 None(그 줄을 뺀다)."""
    qs = BnkSale.objects.filter(day__range=(start, end))
    sums = bnk_sales._sums(qs)
    top = []
    for r in (qs.values('isbn').annotate(n=Sum('total'), name=Max('title'), book=Max('book__title'),
                                         **{k: Sum(k) for k in bnk_sales.STORE_KEYS})
              .order_by('-n', 'name')[:TOP_BOOKS]):
        if r['n'] > 0:
            top.append((r['book'] or r['name'], r['n'],
                        {bnk_sales.STORE_LABEL[k]: r[k] or 0 for k in bnk_sales.STORE_KEYS}))
    try:
        t = client.totals(start, end)
        channels = {'pc': t['pc'], 'mobile': t['mobile'], 'offline': t['offline']}
    except Exception:
        log.warning('monthly: sales channels failed', exc_info=True)
        channels = None
    try:
        readers = client.readers(start, end)
    except Exception:
        log.warning('monthly: readers failed', exc_info=True)
        readers = None
    return {'total': sums['total'], 'stores': {bnk_sales.STORE_LABEL[k]: sums[k] for k in bnk_sales.STORE_KEYS},
            'weeks': _weeks(start, end), 'kinds': qs.values('isbn').distinct().count(), 'top': top,
            'channels': channels, 'readers': readers}


# ---- 있었던 일 후보 ----

def _signals(kind, start, end, dated=True):
    """관련 있고 민감하지 않은 신호 가운데 그 달 것. 날짜가 있으면 날짜로, 없으면 찾은 날로 본다."""
    out = []
    for s in Signal.objects.filter(kind=kind, relevant=True, sensitive=False).select_related('book').order_by('id'):
        day = (s.happens_on if dated else None) or kst_today(s.found_at)
        if start <= day <= end and (s.detail or {}).get('status') != 'cancelled':
            out.append((day, s))
    return out


def events(start, end):
    found = []
    for day, s in _signals(Signal.MOMENT, start, end):
        summary = (s.detail or {}).get('summary', '')
        found.append((day, f'{s.title} — {summary}' if summary else s.title, '검수 방'))
    for s in Signal.objects.filter(kind=Signal.SOCIAL, relevant=True, sensitive=False).order_by('id'):
        try:
            day = date.fromisoformat((s.detail or {}).get('posted_on', ''))
        except ValueError:
            continue
        if start <= day <= end:
            found.append((day, s.detail.get('summary', ''), sns_where(s)))
    for day, s in _signals(Signal.NEWS, start, end):
        d = s.detail or {}
        head = f'『{s.book.title}』 관련 뉴스' if s.book else '뉴스'
        found.append((day, f'{head} 〈{d.get("source", "")}〉 「{s.title}」' + (f' — {d["summary"]}' if d.get('summary') else ''),
                      '뉴스 검색'))
    for day, s in _signals(Signal.SELECTION, start, end):
        found.append((day, f'『{s.book.title}』 {s.title} 선정' if s.book else f'{s.title} 선정', '공공 선정 발표'))
    for camp in FundingCampaign.objects.filter(is_ours=True).order_by('starts_at'):
        snap = FundingSnapshot.objects.filter(campaign=camp, date__lte=end).order_by('-date').first()
        began = camp.starts_at and start <= kst_today(camp.starts_at) <= end
        if not began and not (snap and snap.date >= start):
            continue
        end_on = ends_on(camp)
        parts = ([f'목표의 {snap.percent}%', f'{snap.books}권'] if snap else []) + [f'{end_on.month}월 {end_on.day}일 마감']
        found.append((kst_today(camp.starts_at) if began else None,
                      f'『{_book_name(camp.title)}』 북펀드 {"시작" if began else "진행"} — ' + ', '.join(parts),
                      '알라딘 북펀드 페이지'))
    for g in GrantCall.objects.filter(sent_at__isnull=False).order_by('sent_at'):
        day = kst_today(g.sent_at)
        if start <= day <= end:
            note = {GrantCall.APPLYING: ' — 신청하기로 함', GrantCall.PASSED: ' — 이번엔 넘김'}.get(g.state, '')
            found.append((day, f'{g.title} 알림{note}', '출판진흥원 공고'))
    for b in Book.objects.filter(is_published=True, published_date__range=(start, end)).order_by('published_date'):
        found.append((b.published_date, f'『{b.title}』 출간', '사이트 도서 정보'))
    for item in ReviewItem.objects.filter(status=ReviewItem.APPLIED, book__isnull=False).select_related('book'):
        day = kst_today(item.updated_at)
        if start <= day <= end and any(c[1] == '판매 상태' and c[3] is False for c in item.changed or []):
            found.append((day, f'『{item.book.title}』 종이책 절판 처리', '검수 방 확인'))
    reviews = {}
    for _, s in _signals(Signal.REVIEW, start, end, dated=False):
        if s.book:
            reviews[s.book.title] = reviews.get(s.book.title, 0) + 1
    if reviews:
        ranked = sorted(reviews.items(), key=lambda x: -x[1])
        found.append((None, f'새 독자 서평 {sum(reviews.values())}건 (' + ', '.join(f'『{t}』 {n}' for t, n in ranked[:5]) + ')',
                      '블로그·카페 검색'))
    found.sort(key=lambda x: (x[0] is None, x[0] or date.max))
    return [Item(i, day, text, source) for i, (day, text, source) in enumerate(found, 1) if text]


# ---- 우리가 올린 글 ----

def _blog():
    try:
        return parse_rss(fetch_rss(timeout=10), limit=50)
    except Exception:
        log.warning('monthly: blog rss failed', exc_info=True)
        return None


def posts(start, end, fetch_meta=meta.official_posts, fetch_blog=_blog):
    since = datetime.combine(start, time.min, tzinfo=KST)
    until = datetime.combine(end + timedelta(days=1), time.min, tzinfo=KST)
    try:
        official = fetch_meta(since) or {}
    except Exception:
        log.warning('monthly: official posts failed', exc_info=True)
        official = {}
    out, samples = {}, []
    for ch, label in PLATFORMS:
        rows = official.get(ch)
        if rows is None:
            out[ch] = None
            continue
        rows = [r for r in rows if since <= r.posted_at < until]
        out[ch] = len(rows)
        samples += [f'{label}: {" ".join((r.text or "").split())[:60]}' for r in rows[:8]]
    blog = fetch_blog()
    out['blog'] = None if blog is None else sum(1 for p in blog if p.date and start <= p.date <= end)
    posted = (Draft.objects.filter(status=Draft.POSTED, posted_at__gte=since, posted_at__lt=until)
              .select_related('proposal').order_by('posted_at'))
    out.update(samples=samples, posted=list(dict.fromkeys(d.proposal.headline for d in posted)))
    return out


# ---- 다음 달 준비 ----

def next_month(start):
    end = month_end(start)
    found = []
    for hook in HookDate.objects.prefetch_related('books').order_by('id'):
        on = hook.next_on(start)
        if on and on <= end:
            books = ' '.join(f'『{b.title}』' for b in hook.books.all() if b.is_published)
            found.append((on, f'{on.month}/{on.day} {hook.name}' + ('(추모)' if hook.memorial else '')
                          + (f' {books}' if books else '')))
    for s in Signal.objects.filter(kind=Signal.MOMENT, relevant=True, sensitive=False, happens_on__range=(start, end)):
        if (s.detail or {}).get('status') != 'cancelled':
            found.append((s.happens_on, f'{s.happens_on.month}/{s.happens_on.day} {s.title}'))
    for camp in FundingCampaign.objects.filter(is_ours=True):
        day = ends_on(camp)
        if start <= day <= end:
            found.append((day, f'{day.month}/{day.day} 『{_book_name(camp.title)}』 북펀드 마감'))
    for g in GrantCall.objects.filter(state__in=GrantCall.OPEN, apply_until__range=(start, end)):
        clock = _clock((g.verdict or {}).get('until_time', ''))
        found.append((g.apply_until, f'{g.apply_until.month}/{g.apply_until.day}' + (f' {clock}' if clock else '')
                      + f' {g.title} 신청 마감' + (' (신청하기로 함)' if g.state == GrantCall.APPLYING else '')))
    found.sort(key=lambda x: x[0])
    return [text for _, text in found]
