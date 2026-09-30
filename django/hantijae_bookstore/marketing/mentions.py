"""구글 알리미·유튜브에서 한티재 책 이야기 찾기(스펙 §2 alerts·youtube). 서평 길(Signal kind=review, 출처 web·youtube)로 넣는다.
알리미 글은 모든 공개 도서와, 유튜브는 오늘 순번 책(책마다 주 1회)의 최근 14일 영상만 그 책과 대조한다.
피드 주소·유튜브 키는 비밀이라 로그·알림에 넣지 않는다."""
import logging
import time
from datetime import datetime, timedelta

from django.conf import settings

from books.models import Book
from marketing import reviews
from marketing.http import http_get_bytes, http_get_json
from marketing.models import Signal
from marketing.review_filter import excluded, mentions_book, queries, terms
from marketing.timeutil import KST
from marketing.web_sources import SourceError, feeds, parse_alerts, youtube_search

log = logging.getLogger('intake')
OWN_SITE = 'hantijae-bookstore.com'
SPACING = 0.5
YOUTUBE_GIVE_UP = 3   # 연속 실패 — 한도 초과(403)일 수 있어 그날 유튜브는 멈춘다


def _consider(post, t, today, report, fresh, seen):
    if OWN_SITE in post.url or excluded(post) or not mentions_book(post, t):
        return
    key = reviews.signal_key(t.book, post)
    if key in seen or Signal.objects.filter(key=key).exists():
        return
    seen.add(key)
    if post.posted_on and post.posted_on >= today - timedelta(days=reviews.FRESH_DAYS):
        fresh.append((t, post, key))
    else:
        reviews.save_old(t.book, post, key)
        report.baseline += 1


def scan(today, books=None, cfg=None, get_bytes=http_get_bytes, get_json=http_get_json, sleep=time.sleep):
    cfg = getattr(settings, 'MARKETING', {}) if cfg is None else cfg
    report, fresh, seen = reviews.Report(), [], set()
    urls, key = feeds(cfg), cfg.get('YOUTUBE_API_KEY') or ''
    if not urls and not key:
        return report, fresh
    all_terms = [terms(b) for b in Book.objects.filter(is_published=True).prefetch_related('authors__author')]
    if urls:
        ok = 0
        for i, url in enumerate(urls):
            try:
                posts = parse_alerts(get_bytes(url))
            except Exception as e:   # 피드 주소는 비밀 — 몇 번째 피드인지만
                log.warning('google alerts feed %d failed: %s', i + 1, type(e).__name__)
                continue
            ok += 1
            for p in posts:
                for t in all_terms:
                    _consider(p, t, today, report, fresh, seen)
        if not ok:
            report.failed.append('web')
    if key:
        books = reviews.todays_books(today) if books is None else books
        after = datetime.combine(today - timedelta(days=reviews.FRESH_DAYS), datetime.min.time(), tzinfo=KST)
        streak = 0
        for i, book in enumerate(books):
            if streak >= YOUTUBE_GIVE_UP:
                break
            if i:
                sleep(SPACING)
            t = terms(book)
            try:
                videos = youtube_search(queries(t)[-1], key, after, get_json)
            except SourceError as e:
                streak += 1
                log.warning('youtube search failed: %s', e)
                continue
            streak = 0
            for p in videos:
                _consider(p, t, today, report, fresh, seen)
        if streak >= YOUTUBE_GIVE_UP:
            report.failed.append('youtube')
    report.books = len(all_terms)
    report.found = len(fresh)
    return report, fresh


def run(deps, today, notify, **scan_kwargs):
    """워커가 매일 04:40에 부른다. 모든 알리미 피드 실패·유튜브 연속 실패는 관리자에게(밤이면 08시에) 한 번."""
    report, fresh = scan(today, **scan_kwargs)
    report = reviews.save_judged(deps.llm, fresh, report)
    if 'web' in report.failed:
        notify('⚠️ 구글 알리미 피드를 읽지 못했어요 — 서버 로그의 google alerts 줄을 확인해 주세요')
    if 'youtube' in report.failed:
        notify('⚠️ 유튜브 검색이 연달아 실패해 오늘은 멈췄어요(사용 한도일 수 있어요) — 서버 로그의 youtube 줄을 확인해 주세요')
    return report
