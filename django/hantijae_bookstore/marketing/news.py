"""저자 소식. 사이드카 웹 검색은 실명 검색 금지 정책 때문에 쓰지 못한다(스펙 §6.4 스파이크).
그래서 구글 뉴스 RSS로 모으고(LLM 없음), 판정만 LLM(/complete, 도구 없음)에 한 번에 맡긴다.

좁히기(2026-09-30): 이름만으로 찾으면 동명이인(마포구청장 박강수, 야구선수 최정…) 기사가 위를 채워 저자 기사가
밀려난다(90건 중 관련 6건, 박강수의 EBS·대구CBS 공연 기사를 놓침). 책이 연결된 질의마다 분야 낱말을 LLM으로
한 번 골라 '"이름" (가수 OR 노래 OR 한티재 OR "책 제목")'처럼 찾는다. 관리자는 /watch 이름 + 조건 으로 고친다."""
import hashlib
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import List
from xml.etree import ElementTree

from django.utils import timezone

from books.models import Book, BookAuthor
from intake.llm import complete_json
from marketing.http import http_get
from marketing.models import Signal, WatchQuery
from marketing.prompts import NARROW_SYSTEM, NEWS_FILTER_SYSTEM, build_narrow_user, build_news_user

log = logging.getLogger('intake')

RSS_URL = 'https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko'
NOT_NEWS_EXACT = {'youtube', 'x', 'instagram', 'facebook', 'threads'}
NOT_NEWS_PART = ('브런치', 'brunch', '블로그', 'blog', '티스토리', 'tistory', '카페', 'cafe', '포스트')
PER_QUERY, PER_LLM_CALL = 15, 40
NARROW_MAX_WORDS, NARROW_WORD_MAX, NARROW_INTRO = 6, 12, 400
_WORD = re.compile(r'[0-9A-Za-z가-힣·]+')  # 따옴표·괄호·'-'·띄어쓰기가 들어간 낱말은 검색 문법을 깨므로 버린다


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


def _role(watch):
    ba = watch.book.authors.filter(author__name=watch.query).first()
    return BookAuthor.TYPE_TO_KOREAN.get(ba.author_type, '저자') if ba else '관련 인물·단체'


def _intro(book):
    return ' '.join((book.description or book.short_description or '').split())[:NARROW_INTRO]


def _words(values, name):
    out = []
    for v in values if isinstance(values, list) else []:
        w = str(v).strip()
        if (not _WORD.fullmatch(w) or len(w) > NARROW_WORD_MAX or w.upper() in ('OR', 'AND')
                or w in (name, '한티재') or w in out):
            continue
        out.append(w)
    return out[:NARROW_MAX_WORDS]


def narrow_text(words, book):
    """낱말이 없으면 빈 문자열(이름만으로 찾기). 있으면 한티재와 책 제목도 함께 — 책을 다룬 기사는 분야 낱말이 없어도 잡힌다."""
    if not words:
        return ''
    title = book.title.replace('"', '').strip()
    return '(' + ' OR '.join([*words, '한티재', f'"{title}"']) + ')'


def narrow_new(llm, watches, now):
    """책이 연결됐는데 아직 조건을 정하지 않은 질의를 LLM 한 번으로 좁힌다. 실패하면 이번엔 이름만으로 찾고 다음에 다시."""
    todo = [w for w in watches if w.book_id and w.narrowed_at is None]
    if not todo:
        return
    rows = [(i, w.query, _role(w), _book_line(w.book), _intro(w.book)) for i, w in enumerate(todo)]
    try:
        out = complete_json(llm, NARROW_SYSTEM, build_narrow_user(rows))
    except Exception:
        log.warning('저자 소식 검색어 좁히기 실패(이름만으로 찾음)', exc_info=True)
        return
    by_id = {v.get('id'): v for v in out.get('items', []) if isinstance(v, dict)}
    for i, w in enumerate(todo):
        if i not in by_id:  # 답에서 빠진 사람은 다음 수집 때 다시 묻는다
            continue
        w.narrow, w.narrowed_at = narrow_text(_words(by_id[i].get('words'), w.query), w.book), now
        w.save(update_fields=['narrow', 'narrowed_at', 'updated_at'])


def search_text(watch, days):
    return ' '.join(p for p in (f'"{watch.query}"', watch.narrow, f'when:{days}d') if p)


def collect_news(today, llm, get=http_get, sleep=time.sleep, spacing=2.0, days=14):
    ensure_watch_queries(today)
    rows, seen, failed = [], set(), 0
    watches = list(WatchQuery.objects.filter(active=True).select_related('book').order_by('id'))
    narrow_new(llm, watches, timezone.now())
    for i, watch in enumerate(watches):
        if i:
            sleep(spacing)
        q = urllib.parse.quote(search_text(watch, days))
        try:
            articles = [a for a in parse_rss(get(RSS_URL.format(q=q))) if is_news(a)]
        except Exception:  # 질의 하나 실패는 건너뛴다
            failed += 1
            continue
        for a in articles[:PER_QUERY]:
            key = _key(a.link)
            if key in seen or Signal.objects.filter(key=key).exists():
                continue
            seen.add(key)
            rows.append((watch, a))
    if watches and failed == len(watches):  # 구글이 막았을 수 있다 → 스케줄러의 _guard가 하루 한 번 알린다
        raise RuntimeError(f'구글 뉴스 질의 {failed}개가 모두 실패했어요')
    made = []
    for start in range(0, len(rows), PER_LLM_CALL):
        chunk = rows[start:start + PER_LLM_CALL]
        verdicts = complete_json(llm, NEWS_FILTER_SYSTEM,
                                 build_news_user([(i, w.query, _book_line(w.book), a) for i, (w, a) in enumerate(chunk)]))
        by_id = {v.get('id'): v for v in verdicts.get('items', []) if isinstance(v, dict)}
        for i, (watch, a) in enumerate(chunk):
            v = by_id.get(i, {})
            same_person = bool(v.get('same_person'))  # 동명이인의 부고로 관리자를 놀라게 하지 않는다
            made.append(Signal.objects.create(
                kind=Signal.NEWS, key=_key(a.link), book=watch.book, title=a.title[:500], url=a.link[:1000],
                happens_on=a.published,
                detail={'source': a.source, 'query': watch.query, 'summary': v.get('summary', ''),
                        'evidence': v.get('evidence', ''), 'same_person': same_person},
                relevant=same_person and bool(v.get('relevant')), sensitive=same_person and bool(v.get('sensitive'))))
    return made
