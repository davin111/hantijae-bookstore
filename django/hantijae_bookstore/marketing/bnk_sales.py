"""전산망 판매(marketing.bnk)를 매일 DB에 쌓고, 브리핑 첫 줄·판매 급증·올린 글 효과·월간 요약에 쓸 값을 계산한다.
스펙 .claude/docs/specs/2026-09-30-bnk-sales-design.md (로컬)."""
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

from django.db import transaction
from django.db.models import Max

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
