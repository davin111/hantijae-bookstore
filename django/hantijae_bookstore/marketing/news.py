"""저자 소식. 사이드카 웹 검색은 실명 검색 금지 정책 때문에 쓰지 못한다(스펙 §6.4 스파이크).
그래서 구글 뉴스 RSS로 모으고(LLM 없음), 판정만 LLM(/complete, 도구 없음)에 한 번에 맡긴다."""
import hashlib
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import List
from xml.etree import ElementTree

from books.models import Book
from intake.llm import complete_json
from marketing.http import http_get
from marketing.models import Signal, WatchQuery
from marketing.prompts import NEWS_FILTER_SYSTEM, build_news_user

RSS_URL = 'https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko'
NOT_NEWS_EXACT = {'youtube', 'x', 'instagram', 'facebook', 'threads'}
NOT_NEWS_PART = ('브런치', 'brunch', '블로그', 'blog', '티스토리', 'tistory', '카페', 'cafe', '포스트')
PER_QUERY, PER_LLM_CALL = 15, 40


@dataclass
class Article:
    title: str
    link: str
    source: str
    published: date


def parse_rss(xml_text) -> List[Article]:
    items = []
    for it in ElementTree.fromstring(xml_text.encode('utf-8')).iter('item'):
        title = (it.findtext('title') or '').strip()
        link = (it.findtext('link') or '').strip()
        source = (it.findtext('source') or '').strip()
        try:
            published = parsedate_to_datetime(it.findtext('pubDate') or '').date()
        except (TypeError, ValueError, IndexError):
            continue
        if not title or not link:
            continue
        if source and title.endswith(' - ' + source):  # 구글 뉴스 제목 끝의 ' - 매체명'
            title = title[: -len(' - ' + source)]
        items.append(Article(title, link, source, published))
    return items


def is_news(article):
    s = article.source.lower()
    return s not in NOT_NEWS_EXACT and not any(p in s for p in NOT_NEWS_PART)


def _key(link):
    return 'news:' + hashlib.sha1(link.encode()).hexdigest()


def ensure_watch_queries(today):
    """최근 2년 공개 도서의 저자·단체를 질의로 넣는다(이미 있으면 그대로 둔다)."""
    since = today - timedelta(days=730)
    for book in Book.objects.filter(is_published=True, published_date__gte=since).prefetch_related('authors__author'):
        for ba in book.authors.all():
            WatchQuery.objects.get_or_create(query=ba.author.name, defaults={'book': book})


def _book_line(book):
    return f'『{book.title}』 {book.subtitle}'.strip() if book else '(책 미지정)'


def collect_news(today, llm, get=http_get, sleep=time.sleep, spacing=2.0, days=14):
    ensure_watch_queries(today)
    rows, seen = [], set()
    for i, watch in enumerate(WatchQuery.objects.filter(active=True).select_related('book').order_by('id')):
        if i:
            sleep(spacing)
        q = urllib.parse.quote(f'"{watch.query}" when:{days}d')
        try:
            articles = [a for a in parse_rss(get(RSS_URL.format(q=q))) if is_news(a)]
        except Exception:  # 질의 하나 실패는 건너뛴다
            continue
        for a in articles[:PER_QUERY]:
            key = _key(a.link)
            if key in seen or Signal.objects.filter(key=key).exists():
                continue
            seen.add(key)
            rows.append((watch, a))
    made = []
    for start in range(0, len(rows), PER_LLM_CALL):
        chunk = rows[start:start + PER_LLM_CALL]
        verdicts = complete_json(llm, NEWS_FILTER_SYSTEM,
                                 build_news_user([(i, w.query, _book_line(w.book), a) for i, (w, a) in enumerate(chunk)]))
        by_id = {v.get('id'): v for v in verdicts.get('items', []) if isinstance(v, dict)}
        for i, (watch, a) in enumerate(chunk):
            v = by_id.get(i, {})
            made.append(Signal.objects.create(
                kind=Signal.NEWS, key=_key(a.link), book=watch.book, title=a.title[:500], url=a.link[:1000],
                happens_on=a.published,
                detail={'source': a.source, 'query': watch.query, 'summary': v.get('summary', ''),
                        'evidence': v.get('evidence', '')},
                relevant=bool(v.get('same_person') and v.get('relevant')), sensitive=bool(v.get('sensitive'))))
    return made
