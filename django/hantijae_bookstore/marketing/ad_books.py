"""광고 글이 어느 책 이야기인지 정하기(marketing.ads). 스펙 .claude/docs/specs/2026-10-03-ads-collector-design.md §5-3(로컬),
2026-10-03 보완(사용자: "게시물 내용 보면 알 수 있는 거 아니야?").
후보는 사이트 공개 도서와, 사이트 도서 목록에 아직 없는 우리 북펀드 책(이름만, Ad.book_title). 글자 맞추기로 못 찾은 글은
AI에게 광고마다 한 번 묻는다. 책이 빈 광고는 매일 다시 맞춰 본다 — 북펀드 책이 출간돼 사이트에 올라오면 지난 광고도 이어진다."""
import logging
import re
from dataclasses import dataclass, field
from typing import List

from django.utils import timezone

from marketing.models import Ad
from marketing.text import loose_key

log = logging.getLogger('intake')
MIN_KEY = 3   # 이보다 짧은 제목은 글 속 흔한 말과 겹친다(instagram.MIN_TITLE_KEY와 같다)
ASK_PER_RUN = 5   # 한 번 실행에 AI에게 묻는 광고 수(워커가 한 스레드라 텔레그램 응답이 늦어지지 않게)
_BRACKET = re.compile(r'[<《『〈「]([^<>《》『』〈〉「」]+)[>》』〉」]')
_SUBTITLE = re.compile(r'\s+[-–—:]\s+|:\s+')


def funding_book_title(title):
    """펀딩 제목에서 책 제목만: '<프루동 평전> 국내 최초 번역 출판' → '프루동 평전', '농부, 짠한 형 - 두물머리 …' → '농부, 짠한 형'."""
    m = _BRACKET.search(title or '')
    return (m.group(1) if m else _SUBTITLE.split(title or '', maxsplit=1)[0]).strip()


@dataclass(frozen=True)
class Candidate:
    book: object   # books.Book, 사이트에 아직 없는 북펀드 책이면 None
    title: str
    about: str     # AI에게 보일 설명(부제·지은이 또는 펀딩 제목)


def candidates():
    """사이트 공개 도서 + 우리 북펀드 가운데 사이트 도서 목록에 아직 없는 책(제목은 loose_key로 견준다)."""
    from books.models import Book
    from intake.models import FundingCampaign
    books = list(Book.objects.filter(is_published=True).prefetch_related('authors__author').order_by('-published_date'))
    out = [Candidate(b, b.title, ' · '.join(x for x in (b.subtitle or '', ', '.join(
        ba.author.name for ba in b.authors.all())) if x)) for b in books]
    site = {k for k in (loose_key(b.title) for b in books) if len(k) >= MIN_KEY}
    seen = set()
    for f in FundingCampaign.objects.filter(is_ours=True).order_by('-id'):
        title = funding_book_title(f.title)
        key = loose_key(title)
        # 사이트 제목과 겹치면(같거나 서로 들어 있으면) 그 책은 사이트 책으로 본다 — 한 글이 두 후보에 걸리지 않게
        if len(key) < MIN_KEY or key in seen or any(k in key or key in k for k in site):
            continue
        seen.add(key)
        out.append(Candidate(None, title[:200], f'{f.title} (북펀드)'))
    return out


def _placement_book(ids):
    from marketing.models import Draft
    ids = {i for i in ids if i}
    if not ids:
        return None
    for d in Draft.objects.filter(status=Draft.POSTED, proposal__book__isnull=False).select_related('proposal__book'):
        if any(p.get('id') in ids for p in d.placements or []):
            return d.proposal.book
    return None


def match(ids, text, cands=None):
    """(사이트 책 또는 None, 사이트에 없는 책 제목 또는 ''). 봇 초안의 게시 위치와 같은 글이면 그 책, 아니면 글 속 제목이
    후보 하나와 맞을 때 그 후보. 둘 이상 맞거나 하나도 없으면 (None, '')."""
    book = _placement_book(ids)
    if book is not None:
        return book, ''
    k = loose_key(text)
    hits = {}
    for c in candidates() if cands is None else cands:
        key = loose_key(c.title)
        if len(key) >= MIN_KEY and key in k:
            hits[c.book.pk if c.book is not None else key] = c   # 같은 제목 책이 둘이면 정하지 않는다
    if len(hits) != 1:
        return None, ''
    c = next(iter(hits.values()))
    return (c.book, '') if c.book is not None else (None, c.title)


def ask(llm, text, cands):
    """AI에게 후보 번호 하나와 그 제목을 묻는다. 번호와 제목이 맞으면 그 후보, 번호만 어긋났으면 제목이 같은 후보,
    고르지 않았거나(null) 어느 쪽도 맞지 않으면 None. AI 오류는 그대로 올린다(호출부가 판단)."""
    from intake.llm import complete_json
    from marketing.prompts import AD_BOOK_SYSTEM, build_ad_book_user
    raw = complete_json(llm, AD_BOOK_SYSTEM, build_ad_book_user(text, cands))
    if not isinstance(raw, dict):
        return None
    n, title = raw.get('book'), loose_key(str(raw.get('title') or ''))
    if isinstance(n, str) and n.strip().isdigit():
        n = int(n)
    if isinstance(n, bool) or not isinstance(n, int):
        return None
    if 1 <= n <= len(cands) and (not title or loose_key(cands[n - 1].title) == title):
        return cands[n - 1]
    same = [c for c in cands if title and loose_key(c.title) == title]
    return same[0] if len(same) == 1 else None


@dataclass
class Relinked:
    linked: int = 0    # 책이나 책 제목이 새로 정해진 광고
    asked: int = 0     # AI에게 물은 광고
    failed: int = 0    # AI 연결 오류(이번 실행은 거기서 그만 묻고, 다음에 다시)
    changed: List[int] = field(default_factory=list)   # 바뀐 광고 pk


def _site_book_for_title(title, cands):
    """이미 정한 책 제목(북펀드·AI)과 같은 제목의 사이트 책이 생겼으면 그 책(하나일 때만)."""
    key = loose_key(title)
    books = {c.book.pk: c.book for c in cands if c.book is not None and loose_key(c.title) == key}
    return next(iter(books.values())) if len(books) == 1 else None


def relink(llm=None):
    """책이 빈 광고를 다시 맞춘다. 글자 맞추기는 매번(사이트에 새로 올라온 책·북펀드), 이미 정한 책 제목은 같은 제목의 사이트 책이
    생기면 그 책으로. 그래도 없고 제목도 없는 글은 AI에게 광고마다 한 번(book_asked_at), 한 실행에 ASK_PER_RUN개까지 묻는다.
    AI 연결 오류가 나면 이번 실행은 거기서 그만 묻는다(다음에 다시). 답이 끝내 JSON이 아니면 물은 것으로 친다.
    글 내용을 못 읽은 광고는 건너뛴다. 저장은 그사이 운영자가 책을 고르지 않았을 때만 한다."""
    from intake.llm import LLMInvalidJSON
    result = Relinked()
    todo = list(Ad.objects.filter(book__isnull=True).exclude(post_text=''))
    if not todo:
        return result
    cands = candidates()
    ai_on = llm is not None
    for ad in todo:
        book, title = match((ad.post_id, ad.ig_media_id), ad.post_text, cands)
        if book is None and not title and ad.book_title:
            book = _site_book_for_title(ad.book_title, cands)
        changes = {}
        if (book is None and not title and not ad.book_title and ai_on and ad.book_asked_at is None
                and result.asked < ASK_PER_RUN):
            result.asked += 1
            try:
                picked = ask(llm, ad.post_text, cands)
            except LLMInvalidJSON:   # 이 글에 대한 답이 끝내 모양을 못 갖춤 — 매일 다시 묻지 않는다
                log.warning('ads book ask: answer was not JSON')
                picked = None
            except Exception as e:   # 연결 오류: 글 내용은 로그에 남기지 않는다
                log.warning('ads book ask: %s', type(e).__name__)
                result.failed += 1
                ai_on = False
                continue
            changes['book_asked_at'] = timezone.now()
            if picked is not None:
                book, title = (picked.book, '') if picked.book is not None else (None, picked.title)
        if book is not None:
            changes.update(book=book, book_title='')
        elif title and title != ad.book_title:
            changes['book_title'] = title[:200]
        if not changes:
            continue
        saved = Ad.objects.filter(pk=ad.pk, book__isnull=True).update(updated_at=timezone.now(), **changes)
        if saved and ('book' in changes or 'book_title' in changes):
            result.linked += 1
            result.changed.append(ad.pk)
    return result
