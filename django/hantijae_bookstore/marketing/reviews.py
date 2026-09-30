"""독자 서평 수집(스펙 §4, 결정 B): 책마다 네이버·카카오에서 찾고 → 코드로 1차 거르기 → 새 글만 LLM 1회 판별 → Signal(kind=review)."""
import hashlib
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Tuple

from django.conf import settings

from books.models import Book
from intake.llm import complete_json
from intake.models import WorkerState
from marketing.http import http_get_json
from marketing.models import Signal
from marketing.prompts import REVIEW_JUDGE_SYSTEM, build_review_user
from marketing.review_filter import excluded, mentions_book, queries, terms
from marketing.review_search import SOURCE_LABEL, normalize_url, sources

log = logging.getLogger('intake')
VERDICTS = ('review', 'promo', 'unrelated')
PER_LLM_CALL = 40

FRESH_DAYS = 14
ROTATION = 7      # 책마다 주 1회: 날마다 id % 7이 맞는 책만
SPACING = 0.5
SOURCE_GIVE_UP = 3   # 한 출처가 이만큼 연달아 실패하면 그날 나머지는 부르지 않는다(20초 타임아웃이 걸리면 워커를 오래 붙잡는다)
SCANNED = 'review_scanned_books'   # 한 번이라도 검색이 성공한 (책, 출처). 날짜 없는 글은 그 출처의 첫 검색 결과를 기준선으로만 둔다


def _book_line(t):
    names = ', '.join(ba.author.name for ba in t.book.authors.all())
    sub = f' ― {t.book.subtitle}' if t.book.subtitle else ''
    return f'『{t.title}』{sub} (지은이: {names or "모름"})'


def judge(llm, rows):
    """rows: [(BookTerms, Post)] → {순번: (verdict, reason)}. 판정이 빠지거나 이상한 글은 넣지 않는다(다음에 다시 판별).
    한 묶음(40건) 호출이 실패하면 그 묶음만 빼고, 모든 묶음이 실패하면 예외."""
    out, failed, batches = {}, 0, 0
    for start in range(0, len(rows), PER_LLM_CALL):
        chunk = rows[start:start + PER_LLM_CALL]
        batches += 1
        user = build_review_user([(i, _book_line(t), SOURCE_LABEL[p.source], p.title, p.snippet, p.posted_on)
                                  for i, (t, p) in enumerate(chunk)])
        try:
            result = complete_json(llm, REVIEW_JUDGE_SYSTEM, user)
        except Exception:
            log.warning('review judge failed', exc_info=True)
            failed += 1
            continue
        for v in result.get('items') or []:
            if not isinstance(v, dict) or v.get('verdict') not in VERDICTS:
                continue
            try:
                i = int(v.get('id'))
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(chunk):
                out[start + i] = (v['verdict'], str(v.get('reason') or '')[:200])
    if batches and failed == batches:
        raise RuntimeError(f'서평 판별 LLM 호출 {failed}번이 모두 실패했어요')
    return out


@dataclass
class Report:
    books: int = 0
    found: int = 0      # 거르기를 통과한 새 글
    baseline: int = 0   # 오래됐거나 첫 검색이라 판별 없이 적어 둔 글
    failed: List[str] = field(default_factory=list)   # 그날 호출이 모두 실패한 출처
    reviews: List[Signal] = field(default_factory=list)
    verdicts: Dict[str, Tuple[str, str]] = field(default_factory=dict)


def todays_books(today):
    return [b for b in Book.objects.filter(is_published=True).prefetch_related('authors__author').order_by('id')
            if b.id % ROTATION == today.toordinal() % ROTATION]


def signal_key(book, post):
    return f'review:{book.id}:' + hashlib.sha1(normalize_url(post.url).encode()).hexdigest()


def _save(book, post, key, verdict, reason):
    s, _ = Signal.objects.get_or_create(key=key, defaults={
        'kind': Signal.REVIEW, 'book': book, 'title': post.title[:500], 'url': post.url[:1000],
        'happens_on': post.posted_on, 'relevant': verdict == 'review',
        'detail': {'source': post.source, 'where': post.where[:100], 'snippet': post.snippet[:200],
                   'verdict': verdict, 'reason': reason}})
    return s


def scan(today, books=None, cfg=None, get_json=http_get_json, sleep=time.sleep):
    """검색하고 코드로 거른다. 오래된 글과 첫 검색의 날짜 없는 글은 바로 기준선으로 적고,
    새 글은 판별하도록 [(BookTerms, Post, key)]로 돌려준다."""
    cfg = getattr(settings, 'MARKETING', {}) if cfg is None else cfg
    srcs = sources(cfg)
    report = Report()
    if not srcs:
        return report, []
    books = todays_books(today) if books is None else books
    scanned = set(WorkerState.get(SCANNED) or [])
    calls, errors, ok, bad, streak = Counter(), Counter(), set(), set(), Counter()
    fresh, seen, waited = [], set(), False
    for book in books:
        t = terms(book)
        report.books += 1
        for source, search, creds in srcs:
            for q in queries(t):
                if streak[source] >= SOURCE_GIVE_UP:   # 사흘째 실패가 아니라 한 바퀴 안에서 연달아 실패 — 매달린 API를 기다리지 않는다
                    bad.add(f'{book.id}:{source}')
                    continue
                if waited:
                    sleep(SPACING)
                waited = True
                calls[source] += 1
                try:
                    posts = search(source, q, creds, get_json)
                except Exception:
                    errors[source] += 1
                    streak[source] += 1
                    bad.add(f'{book.id}:{source}')   # 질의 하나라도 실패하면 그 (책, 출처)는 검색된 것으로 치지 않는다
                    if errors[source] == 1:   # 한도 초과면 수십 번 실패한다 → 출처마다 한 번만 남긴다
                        log.warning('review search failed: %s', source, exc_info=True)
                    continue
                streak[source] = 0
                ok.add(f'{book.id}:{source}')
                for p in posts:
                    key = signal_key(book, p)
                    if key in seen or excluded(p) or not mentions_book(p, t):
                        continue
                    seen.add(key)
                    if Signal.objects.filter(key=key).exists():
                        continue
                    if p.posted_on:
                        is_fresh = p.posted_on >= today - timedelta(days=FRESH_DAYS)
                    else:
                        is_fresh = f'{book.id}:{p.source}' in scanned
                    if is_fresh:
                        fresh.append((t, p, key))
                    else:
                        _save(book, p, key, 'old', '')
                        report.baseline += 1
        # 책마다 적어 둔다 — 워커가 죽어도(배포·OOM) 다시 켰을 때 이미 끝낸 책은 되풀이하지 않는다
        WorkerState.put(SCANNED, sorted(scanned | (ok - bad)))
    report.failed = [s for s in calls if errors[s] == calls[s]]
    report.found = len(fresh)
    return report, fresh


def save_judged(llm, fresh, report):
    """새 글을 판별해 적는다. 판정이 빠진 글은 적지 않는다(다음 검색에서 다시).
    판별이 모두 실패하면 예외 — 기준선은 이미 적었다."""
    if not fresh:
        return report
    verdicts = judge(llm, [(t, p) for t, p, _ in fresh])
    for i, (t, p, key) in enumerate(fresh):
        if i not in verdicts:
            continue
        verdict, reason = verdicts[i]
        s = _save(t.book, p, key, verdict, reason)
        report.verdicts[key] = (verdict, reason)
        if verdict == 'review':
            report.reviews.append(s)
    return report


FAIL_ALERT_DAYS = 3


def _track_failures(notify, failed, active):
    """같은 출처가 사흘 연속 모두 실패하면(키 만료·사용 한도) 관리자에게 한 번 알린다."""
    for source in active:
        key = f'review_fail_{source}'
        if source not in failed:
            WorkerState.put(key, 0)
            continue
        streak = (WorkerState.get(key) or 0) + 1
        WorkerState.put(key, streak)
        if streak == FAIL_ALERT_DAYS:
            notify(f'⚠️ 서평 수집: {SOURCE_LABEL[source]} 검색이 {streak}일째 실패했어요. '
                  f'API 키·사용 한도를 확인해 주세요')


def run(deps, today, notify=None, **scan_kwargs):
    """워커가 하루 한 번(04:30 KST) 부른다. 판별 LLM이 모두 실패하면 예외를 올린다(tasks._guard가 하루 한 번 알림).
    실패 알림은 notify로 보낸다 — 새벽엔 바로 울리지 않게 tasks.py가 조용한 시간 큐를 도는 함수를 건네준다."""
    cfg = getattr(settings, 'MARKETING', {})
    report, fresh = scan(today, cfg=cfg, **scan_kwargs)
    _track_failures(notify or deps.bot.notify_admin, report.failed, [s for s, _, _ in sources(cfg)])
    return save_judged(deps.llm, fresh, report)
