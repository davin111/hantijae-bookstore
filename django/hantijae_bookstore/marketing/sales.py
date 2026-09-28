"""알라딘 판매 지수(세일즈포인트) 수집. 공개 상품 페이지를 하루 한 번, 1.5초 간격으로 읽는다."""
import collections
import re
import time
from dataclasses import dataclass
from typing import Optional

from books.models import Book
from marketing.http import http_get
from marketing.models import BookProfile, SalesSnapshot
from web.presenters import isbn13

PRODUCT_URL = 'https://www.aladin.co.kr/shop/wproduct.aspx?ISBN={isbn}'


@dataclass
class AladinPage:
    sales_point: int
    item_id: str
    short_reviews: int
    reviews: int


def _int(pattern, html):
    m = re.search(pattern, html)
    return int(m.group(1).replace(',', '')) if m else 0


def parse_product(html: str, isbn: str) -> Optional[AladinPage]:
    """페이지의 ISBN이 요청한 것과 같을 때만 값을 믿는다(광고·다른 판 페이지를 막는다)."""
    page_isbn = re.search(r'ISBN : ([0-9X]{13})', html)
    if not page_isbn or page_isbn.group(1) != isbn or 'Sales Point : <strong>' not in html:
        return None
    ids = collections.Counter(re.findall(r'ItemId=(\d+)', html)).most_common(1)
    return AladinPage(sales_point=_int(r'Sales Point : <strong>([0-9,]+)', html),
                      item_id=ids[0][0] if ids else '',
                      short_reviews=_int(r'100자평\((\d+)\)', html),
                      reviews=_int(r"_MyReview'>리뷰\((\d+)\)", html))


def collect_sales(today, get=http_get, sleep=time.sleep, spacing=1.5, books=None):
    """판매 중인 공개 도서의 오늘 값을 저장한다. (저장 수, 실패한 책 제목)을 돌려준다."""
    if books is None:
        books = Book.objects.filter(is_published=True, visible=True).order_by('id')
    saved, failed, asked = 0, [], 0
    for book in books:
        code = isbn13(book.isbn)
        if not code or SalesSnapshot.objects.filter(book=book, date=today).exists():
            continue
        if asked:
            sleep(spacing)
        asked += 1
        try:
            page = parse_product(get(PRODUCT_URL.format(isbn=code)), code)
        except Exception:  # 한 권 실패가 전체를 멈추지 않게
            page = None
        if page is None:
            failed.append(book.title)
            continue
        SalesSnapshot.objects.create(book=book, date=today, sales_point=page.sales_point,
                                     short_reviews=page.short_reviews, reviews=page.reviews)
        if page.item_id:
            BookProfile.objects.update_or_create(book=book, defaults={'aladin_item_id': page.item_id})
        saved += 1
    return saved, failed


def latest(book, on_or_before):
    return SalesSnapshot.objects.filter(book=book, date__lte=on_or_before).order_by('-date').first()
