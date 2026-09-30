"""전산망 판매(marketing.bnk)를 매일 DB에 쌓고, 브리핑 첫 줄·판매 급증·올린 글 효과·월간 요약에 쓸 값을 계산한다.
스펙 .claude/docs/specs/2026-09-30-bnk-sales-design.md (로컬)."""
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

from django.db import transaction
from django.db.models import Max, Sum

from books.models import Book
from intake.models import WorkerState
from marketing.bnk import BnkError, BnkLoginError
from marketing.models import BnkSale
from web.presenters import isbn13

log = logging.getLogger('intake')
MODES = ('on', 'off')
BACKFILL_DAYS = 35   # 처음 켤 때: 급증 기준 4주 + 이번 주
DAILY_DAYS = 7       # 매일: 늦게 들어오는 날짜까지 다시 읽는다
FRESH_DAYS = 10      # 이보다 오래 비어 있으면 전산망 값을 쓰지 않는다(알라딘 기준으로)


def mode():
    return WorkerState.get('bnk_mode', 'off')


@dataclass
class Report:
    days: int = 0
    rows: int = 0
    failed: List[date] = field(default_factory=list)
    latest: Optional[date] = None


def _books_by_isbn():
    out = {}
    for b in Book.objects.exclude(isbn__isnull=True).only('id', 'isbn'):
        code = isbn13(b.isbn)
        if code:
            out.setdefault(code, b)
    return out


def _replace_day(day, rows, books):
    """그날 행을 새 응답으로 바꾼다. 빈 응답인데 이미 행이 있으면(늦게 들어오는 중·일시 오류) 그대로 둔다."""
    if not rows and BnkSale.objects.filter(day=day).exists():
        return 0
    with transaction.atomic():
        BnkSale.objects.filter(day=day).delete()
        BnkSale.objects.bulk_create([
            BnkSale(day=day, isbn=r['isbn'], book=books.get(r['isbn']), title=r['title'], kyobo=r['kyobo'],
                    yes24=r['yes24'], aladin=r['aladin'], ypbooks=r['ypbooks'], local=r['local'], total=r['total'])
            for r in rows])
    return len(rows)


def collect(client, today):
    """어제부터 거꾸로 7일(처음이면 35일)을 날짜마다 바꿔 넣는다. 하루 실패는 건너뛰고, 모두 실패하면 예외.
    로그인이 풀린 오류(BnkLoginError)는 부르는 쪽이 관리자에게 알리도록 그대로 올린다."""
    first = not WorkerState.get('bnk_backfilled')
    books, report = _books_by_isbn(), Report()
    for i in range(1, (BACKFILL_DAYS if first else DAILY_DAYS) + 1):
        day = today - timedelta(days=i)
        try:
            rows = client.sales_on(day)
        except BnkLoginError:
            raise
        except Exception:
            log.warning('bnk day failed: %s', day, exc_info=True)
            report.failed.append(day)
            continue
        report.rows += _replace_day(day, rows, books)
        report.days += 1
    if not report.days:
        raise BnkError('전산망 판매를 하루도 읽지 못했어요')
    if first:
        WorkerState.put('bnk_backfilled', today.isoformat())
    report.latest = latest_day(today)
    return report


def latest_day(today):
    return (BnkSale.objects.filter(day__lte=today, day__gte=today - timedelta(days=FRESH_DAYS))
            .aggregate(m=Max('day'))['m'])


def report_text(report):
    text = (f'읽은 날 {report.days}일 · 판매 줄 {report.rows}개 · 가장 최근 판매일 '
            f'{report.latest.isoformat() if report.latest else "-"}')
    if report.failed:
        text += f' · 못 읽은 날 {len(report.failed)}일(' + ', '.join(d.isoformat() for d in report.failed) + ')'
    return text


STORE_LABEL = {'kyobo': '교보', 'yes24': '예스24', 'aladin': '알라딘', 'ypbooks': '영풍', 'local': '지역서점'}
STORE_KEYS = tuple(STORE_LABEL)
SURGE_MIN, SURGE_RATIO, NEW_BOOK_DAYS, BASE_WEEKS = 5, 3, 60, 4
TOP_STORE_SHARE = 0.6   # 한 서점이 이보다 많으면 괄호로 밝힌다
LOGIN_FAIL = ('⚠️ 출판유통통합전산망에 로그인하지 못했어요. 대표님이 비밀번호를 바꾸셨으면 새 비밀번호를 알려 주세요 '
              '(판매 요약·급증 후보는 알라딘 지수로 돌아가요)')
USAGE = '사용법: /bnk on|off · /bnk now (지금 수집, 처음이면 35일) · /bnk month (지난달 요약 미리 보기)'


def active(today):
    """전산망 값을 쓸 수 있으면 가장 최근 판매일, 아니면 None(꺼짐·10일 넘게 비었음)."""
    return latest_day(today) if mode() == 'on' else None


def _sums(qs):
    agg = qs.aggregate(**{k: Sum(k) for k in STORE_KEYS + ('total',)})
    return {k: agg[k] or 0 for k in STORE_KEYS + ('total',)}


def _top_store(counts):
    """가장 많이 판 서점이 합의 60%를 넘으면 (이름, 수)."""
    total = sum(counts[k] or 0 for k in STORE_KEYS)
    key = max(STORE_KEYS, key=lambda k: counts[k] or 0)
    return (STORE_LABEL[key], counts[key]) if total and counts[key] > total * TOP_STORE_SHARE else None


def _md(d):
    return f'{d.month}월 {d.day}일'


def num(x):
    return ('%.1f' % x).rstrip('0').rstrip('.')


def _by_book(start, end, book_ids=None):
    qs = BnkSale.objects.filter(day__range=(start, end), book__isnull=False)
    if book_ids is not None:
        qs = qs.filter(book__in=book_ids)
    return {r['book']: r for r in qs.values('book').annotate(n=Sum('total'), **{k: Sum(k) for k in STORE_KEYS})}


def sales_line(today):
    end = active(today)
    if not end:
        return ''
    start = end - timedelta(days=6)
    cur = _sums(BnkSale.objects.filter(day__range=(start, end)))['total']
    prev = _sums(BnkSale.objects.filter(day__range=(start - timedelta(days=7), start - timedelta(days=1))))['total']
    diff = cur - prev
    change = f'그 전 7일보다 {abs(diff)}권 {"더" if diff > 0 else "덜"}' if diff else '그 전 7일과 같음'
    line = f'📈 최근 7일({_md(start)}~{_md(end)}) {cur}권 · {change}'
    week = _by_book(start, end)
    books = {b.id: b for b in Book.objects.filter(pk__in=list(week), is_published=True)}
    ranked = sorted((r for r in week.values() if r['book'] in books and r['n'] > 0),
                    key=lambda r: (-r['n'], -books[r['book']].published_date.toordinal()))
    if ranked:
        top = ranked[0]
        store = _top_store(top)
        line += (f' · 가장 많이 팔린 책 『{books[top["book"]].title}』 {top["n"]}권'
                 + (f'({store[0]} {store[1]})' if store else ''))
    return line


def surges(today):
    """최근 7일 판매가 평소(그 전 4주 평균)의 3배 넘고 5권 이상인, 나온 지 60일 넘은 책. 전산망을 못 쓰면 None."""
    end = active(today)
    if not end:
        return None
    start = end - timedelta(days=6)
    week = _by_book(start, end)
    base = {b: r['n'] for b, r in _by_book(start - timedelta(days=7 * BASE_WEEKS), start - timedelta(days=1),
                                           list(week)).items()}
    out = []
    for book in Book.objects.filter(pk__in=list(week), is_published=True, visible=True,
                                    published_date__lte=end - timedelta(days=NEW_BOOK_DAYS)).order_by('id'):
        r = week[book.id]
        usual = (base.get(book.id) or 0) / BASE_WEEKS
        if r['n'] >= SURGE_MIN and r['n'] >= SURGE_RATIO * max(usual, 1):
            out.append({'book': book, 'week': r['n'], 'usual': usual, 'end': end, 'top': _top_store(r),
                        'stores': {STORE_LABEL[k]: r[k] or 0 for k in STORE_KEYS}})
    return out


def around(book, day, today):
    """올린 날 전 2주·뒤 2주(올린 날 포함) 판매 합. 뒤 2주가 아직 다 안 들어왔거나 전산망을 못 쓰면 None."""
    end = active(today)
    if not end or end < day + timedelta(days=13):
        return None
    qs = BnkSale.objects.filter(book=book)
    before = _sums(qs.filter(day__range=(day - timedelta(days=14), day - timedelta(days=1))))['total']
    after = _sums(qs.filter(day__range=(day, day + timedelta(days=13))))['total']
    return before, after


def last_month_start(today):
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


def monthly_text(client, month_start):
    """지난달 요약(관리자 1:1). 기록이 그 달 1일부터 있지 않으면(처음 켠 달) 틀린 합계를 보내지 않게 ''."""
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    if not BnkSale.objects.filter(day__lte=month_start).exists():
        return ''
    qs = BnkSale.objects.filter(day__range=(month_start, month_end))
    s = _sums(qs)
    lines = [f'📊 {month_start.month}월 판매 요약(전산망)',
             f'합계 {s["total"]}권 · ' + ' · '.join(f'{STORE_LABEL[k]} {s[k]}' for k in STORE_KEYS)]
    top = [t for t in qs.values('isbn').annotate(n=Sum('total'), name=Max('title')).order_by('-n', 'name')[:3]
           if t['n'] > 0]
    if top:
        lines.append('많이 팔린 책: ' + ', '.join(f'『{t["name"]}』 {t["n"]}권' for t in top))
    r = client.readers(month_start, month_end)
    if r['buyers']:
        ages = ' · '.join(f'{name} {round(v)}%' for name, v in r['age'][:3])
        regions = ' · '.join(f'{name} {n}' for name, n in r['region'][:3] if n)
        lines.append(f'온라인 구매자: {ages} / 여성 {round(r["female"])}% / {regions}')
    return '\n'.join(lines)


def status_text(today):
    end = latest_day(today)
    week = _sums(BnkSale.objects.filter(day__range=(end - timedelta(days=6), end)))['total'] if end else 0
    return '\n'.join([f'bnk_mode={mode()}', f'bnk_last_run={WorkerState.get("bnk_last_run")}',
                      f'가장 최근 판매일={end.isoformat() if end else "-"}', f'최근 7일 합계={week}권', USAGE])
