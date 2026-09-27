import logging
import re
from urllib.parse import urlparse

from django.conf import settings
from django.db import DatabaseError
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404

from books.models import Book
from web import presenters
from web.models import StoreClick

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
