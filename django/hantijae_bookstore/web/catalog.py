"""공개 도서 조회. 목록은 지은이를 미리 불러와 카드마다 쿼리가 늘지 않게 한다."""
from typing import List, Optional

from django.core.paginator import EmptyPage, Paginator
from django.db.models import Count, OuterRef, Prefetch, Q, Subquery

from books.constants import PUBLIC_SERIES_ORDER
from books.models import Book, BookAuthor, BookSeries, Series

PAGE_SIZE = 24
AUTHORS = Prefetch('authors', queryset=BookAuthor.objects.select_related('author').order_by('id'))


def published_books():
    return Book.objects.filter(is_published=True).prefetch_related(AUTHORS)


def newest_first(qs):
    return qs.order_by('-published_date', '-id')


def published_count() -> int:
    return Book.objects.filter(is_published=True).count()


def public_series() -> List[Series]:
    rows = {s.name: s for s in Series.objects.filter(name__in=PUBLIC_SERIES_ORDER)
            .annotate(book_count=Count('books', filter=Q(books__book__is_published=True)))}
    return [rows[name] for name in PUBLIC_SERIES_ORDER if name in rows]


def get_public_series(series_id: int) -> Optional[Series]:
    return next((s for s in public_series() if s.id == series_id), None)


def all_books():
    return newest_first(published_books())


def recent_books(limit: int, offset: int = 0) -> List[Book]:
    return list(all_books()[offset:offset + limit])


def series_books(series):
    """시리즈의 공개 책, 최신순. 카드에 번호를 달 수 있게 그 시리즈에서의 번호(series_index)를 붙인다."""
    number = BookSeries.objects.filter(book=OuterRef('pk'), series=series).values('index')[:1]
    return newest_first(published_books().filter(series__series=series).annotate(series_index=Subquery(number)))


def paginate(qs, page):
    """존재하지 않거나 이상한 쪽 번호면 None (뷰가 404로 바꾼다)."""
    try:
        number = int(page or 1)
        if number < 1:
            return None
        return Paginator(qs, PAGE_SIZE).page(number)
    except (TypeError, ValueError, EmptyPage):
        return None


def search_books(q: str):
    q = (q or '').strip()
    if not q:
        return published_books().none()
    return newest_first(published_books().filter(
        Q(title__icontains=q) | Q(subtitle__icontains=q) | Q(authors__author__name__icontains=q)).distinct())


def book_with_details(pk: int) -> Optional[Book]:
    """공개 여부와 무관하게 가져온다(미리보기 판단은 뷰에서)."""
    return Book.objects.prefetch_related(AUTHORS, 'series__series').filter(pk=pk).first()


def book_series_entry(book) -> Optional[BookSeries]:
    """책이 속한 첫 공개 시리즈 연결(시리즈 + 번호)."""
    for bs in book.series.all():
        if bs.series.name in PUBLIC_SERIES_ORDER:
            return bs
    return None


def book_series(book) -> Optional[Series]:
    entry = book_series_entry(book)
    return entry.series if entry else None


def same_series_books(book, series, limit: int = 6) -> List[Book]:
    if series is None:
        return []
    return list(series_books(series).exclude(pk=book.pk)[:limit])
