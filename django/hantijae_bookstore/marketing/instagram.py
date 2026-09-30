"""인스타에서 한티재 책 이야기 찾기(스펙 §6): 한티재를 태그한 공개 글(매일)과 협력 계정(책방·단체)의 최근 글(일요일).
찾은 글은 독자 서평과 같은 길(Signal kind=review, 출처 ig_tag·ig_partner)로 들어간다 — 판별 LLM·브리핑 후보·중복 제거를 그대로 쓴다.
개인 계정의 아이디는 저장하지 않는다(business_discovery가 되는 프로페셔널 계정만 '@아이디')."""
import dataclasses
import logging
import re
from datetime import date, timedelta

import requests
from django.conf import settings

from books.models import Book
from intake.models import WorkerState
from marketing import meta, reviews
from marketing.models import Signal
from marketing.review_filter import terms
from marketing.review_search import Post
from marketing.text import loose_key
from marketing.timeutil import KST

log = logging.getLogger('intake')
# 공개 사업자·단체 계정(.claude/docs/signals/2026-09-29/meta-partners.md). 운영진·창작자 개인 계정은 넣지 않는다
PARTNERS = ('hagobooks', 'mulu.books', 'veganbooks_', 'brightbooks_law', 'todakbook', 'gosranhi_breadbook',
            'yeonrip_seoga', 'rainbowmamapapa', 'inmunclub.org_', 'cheonan_ngo_center', 'maposeforus', 'kobic_official')
PARTNER_WEEKDAY = 6   # 일요일 — 월요일 브리핑 전에
MIN_TITLE_KEY = 3     # 이보다 짧은 제목은 캡션 속 흔한 말과 겹친다
EXPIRES_DEFAULT = '2026-12-28'
REMIND_BEFORE = 8
AUTH_NOTE = ('⚠️ Meta(페북·인스타) 연결이 끊겼어요 — 토큰이 만료됐거나 권한이 바뀐 것 같아요. '
             '런북 .claude/docs/meta-api/2026-09-29/00-overview.md 2~4단계로 다시 발급해 주세요')
_HANDLE = re.compile(r'(?<![\w.])@[A-Za-z0-9._]{1,30}')


def book_hits(text, book_terms):
    k = loose_key(text)
    return [t for t in book_terms if len(t.key) >= MIN_TITLE_KEY and t.key in k]


def _post(source, m, where=''):
    caption = _HANDLE.sub('@…', m.caption)   # 책 찾기는 원문 캡션으로 하고(호출부), 저장·LLM에는 아이디를 지운 것만 준다
    first = (caption.strip().splitlines() or [''])[0]
    return Post(source, m.url, first[:80], caption[:200], m.posted_at.astimezone(KST).date(), where)


def _collect(source, medias, today, book_terms, where_of, report, fresh, seen):
    """글마다 책을 찾아 새 글은 fresh에, 오래된 글은 기준선으로. where_of(media)는 새 글에만 부른다."""
    for m in medias:
        for t in book_hits(m.caption, book_terms):
            post = _post(source, m)
            key = reviews.signal_key(t.book, post)
            if key in seen or Signal.objects.filter(key=key).exists():
                continue
            seen.add(key)
            if post.posted_on >= today - timedelta(days=reviews.FRESH_DAYS):
                fresh.append((t, dataclasses.replace(post, where=where_of(m)), key))
            else:
                reviews.save_old(t.book, post, key)
                report.baseline += 1


def scan(today, partners=False, books=None, get=requests.get):
    report, fresh, seen = reviews.Report(), [], set()
    if books is None:
        books = Book.objects.filter(is_published=True).prefetch_related('authors__author')
    book_terms = [terms(b) for b in books]
    report.books = len(book_terms)
    pro = {}

    def tagger(m):
        if m.username and m.username not in pro:
            try:
                pro[m.username] = meta.business_media(m.username, limit=1, get=get) is not None
            except meta.MetaAuthError:
                raise
            except meta.MetaError as e:
                log.warning('instagram tagger check failed: %s', e)
                pro[m.username] = False
        return f'@{m.username}' if m.username and pro[m.username] else ''

    try:
        tags = meta.tagged_media(get=get)
    except meta.MetaAuthError:
        raise
    except meta.MetaError as e:
        log.warning('instagram tags: %s', e)
        report.failed.append('ig_tag')
        tags = []
    _collect('ig_tag', tags, today, book_terms, tagger, report, fresh, seen)
    if partners:
        for handle in PARTNERS:
            try:
                medias = meta.business_media(handle, get=get)
            except meta.MetaAuthError:
                raise
            except meta.MetaError as e:   # 한 계정의 오류는 그 계정만 건너뛴다
                log.warning('instagram partner %s: %s', handle, e)
                continue
            if medias is None:
                log.warning('instagram partner %s: not a professional account', handle)
                continue
            _collect('ig_partner', medias, today, book_terms, lambda m, h=handle: f'@{h}', report, fresh, seen)
    report.found = len(fresh)
    return report, fresh


def _remind_expiry(today, notify):
    cfg = getattr(settings, 'MARKETING', {})
    expires = date.fromisoformat(cfg.get('META_ACCESS_EXPIRES') or EXPIRES_DEFAULT)
    if today >= expires - timedelta(days=REMIND_BEFORE) and WorkerState.get('meta_expiry_reminded') != expires.isoformat():
        WorkerState.put('meta_expiry_reminded', expires.isoformat())
        notify(f'⏰ Meta 인스타 데이터 접근이 {expires.month}월 {expires.day}일에 끝나요. 런북 '
               '.claude/docs/meta-api/2026-09-29/00-overview.md 2~4단계로 미리 다시 발급하고, 새 만료일을 '
               'META_ACCESS_EXPIRES에 적어 주세요')


def run(deps, today, notify, get=requests.get):
    """워커가 매일 부른다(협력 계정은 일요일에만). Meta 권한 오류는 하루 한 번 관리자에게 알리고 None."""
    if not meta.ig_configured():   # 키가 없으면 아무것도 하지 않는다(시험·개발 환경)
        return reviews.Report()
    _remind_expiry(today, notify)
    try:
        report, fresh = scan(today, partners=today.weekday() == PARTNER_WEEKDAY, get=get)
    except meta.MetaAuthError:
        if WorkerState.get('meta_auth_alert_day') != today.isoformat():
            WorkerState.put('meta_auth_alert_day', today.isoformat())
            notify(AUTH_NOTE)
        return None
    result = reviews.save_judged(deps.llm, fresh, report)
    if 'ig_tag' in report.failed:
        raise RuntimeError('인스타 태그 글을 읽지 못했어요(Meta 오류)')
    return result
