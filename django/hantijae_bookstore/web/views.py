import logging
import re
from urllib.parse import quote, urlparse

from django.conf import settings
from django.db import DatabaseError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect

from books.models import Book
from books.preview import is_valid_preview_token
from web import blog, catalog, presenters, site_info
from web.models import StoreClick, current_notice
from web.pages import page_meta, render_page

log = logging.getLogger(__name__)
# 미리보기 수집기·검색 로봇이 링크를 따라와도 클릭으로 세지 않는다
BOT_UA = re.compile(r'bot|crawl|spider|slurp|facebookexternalhit|kakaotalk-scrap|yeti|preview', re.I)


def referrer_host(request) -> str:
    return (urlparse(request.META.get('HTTP_REFERER', '')).hostname or '')[:200]


def store_redirect(request, book_id, store):
    if store not in dict(presenters.STORES):
        raise Http404
    book = get_object_or_404(Book, pk=book_id, is_published=True)
    url = presenters.store_url(book, store)
    if not url:
        raise Http404
    # 로컬 dev 모드는 운영 DB를 보므로 기록하지 않는다
    if not settings.DEBUG and not BOT_UA.search(request.META.get('HTTP_USER_AGENT', '')):
        try:
            StoreClick.objects.create(book=book, store=store, referrer_host=referrer_host(request))
        except DatabaseError:
            log.exception('store click not recorded')
    return HttpResponseRedirect(url)


def home(request):
    series = catalog.public_series()
    books = catalog.recent_books(7)
    hero, recent = (books[0], books[1:]) if books else (None, [])
    shelf_series = series[0] if series else None
    return render_page(request, 'web/home.html', {
        'hero': hero,
        'hero_series': catalog.book_series(hero) if hero else None,
        'hero_links': presenters.store_links(hero) if hero else [],
        'hero_summary': presenters.strip_marks(hero.short_description).strip() if hero else '',
        'recent': recent,
        'shelf_series': shelf_series,
        'shelf_books': list(catalog.series_books(shelf_series)[:12]) if shelf_series else [],
        'notice': current_notice(),
        'blog_posts': blog.latest_posts(),
    }, meta=page_meta('/'), nav_active='home', nav_series=series)


def series_page(request, series_id):
    nav = catalog.public_series()
    series = next((s for s in nav if s.id == int(series_id)), None)
    if series is None:
        raise Http404
    page = catalog.paginate(catalog.series_books(series), request.GET.get('page'))
    if page is None:
        raise Http404
    books = list(page.object_list)
    base_path = f'/series={series.id}'
    path = base_path + (f'?page={page.number}' if page.number > 1 else '')
    meta = page_meta(path, title=series.name, description=f'{series.name} {series.book_count}권 — 도서출판 한티재',
                     image=presenters.cover_3d_url(books[0]) if books else None)
    return render_page(request, 'web/series.html', {'series': series, 'page': page, 'books': books,
                                                    'base_path': base_path}, meta=meta, nav_active=series.id,
                       nav_series=nav)


def book_detail(request, book_id):
    book = catalog.book_with_details(int(book_id))
    if book is None:
        raise Http404
    preview = not book.is_published
    if preview and not is_valid_preview_token(book.id, request.GET.get('preview', '')):
        raise Http404
    series = catalog.book_series(book)
    sections = presenters.parse_description(book.description)
    authors = presenters.authors_of(book)
    spec = [(label, value) for label, value in (
        ('가격', presenters.format_price(book.full_price)),
        ('펴낸 날', presenters.format_date_ko(book.published_date)),
        ('쪽수', f'{book.page_count}쪽' if book.page_count else ''),
        ('판형', presenters.format_size(book.size)),
        ('ISBN', presenters.format_isbn(book.isbn)),
    ) if value]
    code = presenters.isbn13(book.isbn)
    extra = ([('book:isbn', code)] if code else []) + [('book:release_date', book.published_date.isoformat())]
    extra += [('book:author', name) for name, _ in authors]
    meta = page_meta(f'/book={book.id}', title=book.title,
                     description=presenters.short_text(book.short_description or book.description, 150),
                     image=presenters.cover_3d_url(book), og_type='book', noindex=preview, extra=extra)
    return render_page(request, 'web/book_detail.html', {
        'book': book, 'series': series, 'credit': presenters.credit_line(authors), 'spec': spec,
        'links': presenters.store_links(book), 'preview': preview, 'sections': sections,
        'section_nav': sections if len(sections) > 1 else [],
        'video_url': site_info.AUTHOR_VIDEOS.get(book.id),
        'same_series': catalog.same_series_books(book, series),
    }, meta=meta, nav_active=series.id if series else None)


def search_redirect(request):
    q = (request.GET.get('q') or '').strip()
    return redirect('/search=' + quote(q, safe='')) if q else redirect('/')


def search_page(request, q):
    q = q.strip()
    page = catalog.paginate(catalog.search_books(q), request.GET.get('page'))
    if page is None:
        raise Http404
    base_path = '/search=' + quote(q, safe='')
    path = base_path + (f'?page={page.number}' if page.number > 1 else '')
    return render_page(request, 'web/search.html', {
        'query': q, 'page': page, 'books': list(page.object_list), 'base_path': base_path,
        'suggestions': catalog.recent_books(6) if not page.paginator.count else [],
    }, meta=page_meta(path, title=f'‘{q}’ 검색', noindex=True), search_query=q)
