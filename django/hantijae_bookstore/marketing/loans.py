"""도서관 정보나루 대출(스펙 §7): 공개 도서마다 최근 12개월 월별 대출을 읽어 LoanSnapshot에 덮어쓴다. 매주 토요일 새벽.
하루 500건 한도 안(공개 도서 약 170권), 요청 사이 1초. 도서관 자료는 한두 달 늦게 들어온다.
인증 키가 주소에 들어가므로 예외 문구·주소를 로그에 남기지 않는다(예외 종류 이름만)."""
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date

from django.conf import settings

from books.models import Book
from marketing.http import http_get_json
from marketing.models import LoanSnapshot
from marketing.selection_match import isbn13

log = logging.getLogger('intake')
API = 'http://data4library.kr/api/usageAnalysisList'
SPACING = 1.0
NOT_FOUND = 'isbnMpngErr'   # 그 ISBN이 도서관 자료에 없다 — 오류가 아니다
_MONTH = re.compile(r'(\d{4})\D+(\d{1,2})')


@dataclass
class LoanReport:
    books: int = 0     # 물어본 책
    saved: int = 0     # 적은 (책, 달)
    missing: int = 0   # 도서관 자료에 없는 책
    failed: int = 0


def parse_month(text):
    m = _MONTH.match(text or '')
    return date(int(m.group(1)), int(m.group(2)), 1) if m else None


def parse(data):
    """[(달 첫날, 대출 수, 순위|None)]. 도서관 자료에 없는 책이면 None, 다른 오류면 ValueError."""
    resp = (data or {}).get('response') or {}
    if resp.get('errCode') == NOT_FOUND:
        return None
    if resp.get('errCode') or resp.get('error'):
        raise ValueError(f'data4library {resp.get("errCode") or "error"}')
    out = []
    for row in resp.get('loanHistory') or []:
        loan = row.get('loan') or {}
        month = parse_month(loan.get('month'))
        if month:
            ranking = loan.get('ranking')
            out.append((month, int(loan.get('loanCnt') or 0), int(ranking) if ranking else None))
    return out


def collect(today, books=None, key=None, get_json=http_get_json, sleep=time.sleep):
    key = getattr(settings, 'MARKETING', {}).get('DATA4LIBRARY_AUTH_KEY', '') if key is None else key
    report = LoanReport()
    if not key:
        return report
    books = Book.objects.filter(is_published=True).order_by('id') if books is None else books
    first = True
    for book in books:
        isbn = isbn13(book.isbn)
        if not isbn:
            continue
        if not first:
            sleep(SPACING)
        first = False
        report.books += 1
        try:
            rows = parse(get_json(API + '?' + urllib.parse.urlencode({'authKey': key, 'isbn13': isbn, 'format': 'json'})))
        except Exception as e:   # 주소(키)가 담긴 문구는 남기지 않는다
            report.failed += 1
            if report.failed == 1:
                log.warning('data4library %s failed: %s', isbn, type(e).__name__)
            continue
        if rows is None:
            report.missing += 1
            continue
        for month, n, ranking in rows:
            LoanSnapshot.objects.update_or_create(book=book, month=month, defaults={'loans': n, 'ranking': ranking})
            report.saved += 1
    if report.books and report.failed == report.books:
        raise RuntimeError(f'도서관 정보나루를 한 권도 읽지 못했어요({report.failed}권 실패)')
    return report
