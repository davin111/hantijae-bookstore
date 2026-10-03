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
_BRACKET = re.compile(r'[<《『〈「]([^<>《》『』〈〉「」]+)[>》』〉」]')


def funding_book_title(title):
    """펀딩 제목에서 책 제목만: '<프루동 평전> 국내 최초 번역 출판' → '프루동 평전', '농부, 짠한 형 - 두물머리 …' → '농부, 짠한 형'."""
    m = _BRACKET.search(title or '')
    return (m.group(1) if m else (title or '').split(' - ')[0]).strip()


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
    seen = {loose_key(b.title) for b in books}
    for f in FundingCampaign.objects.filter(is_ours=True).order_by('-id'):
        title = funding_book_title(f.title)
        key = loose_key(title)
        if len(key) >= MIN_KEY and key not in seen:
            seen.add(key)
            out.append(Candidate(None, title, f'{f.title} (북펀드)'))
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
            hits[key] = c
    if len(hits) != 1:
        return None, ''
    c = next(iter(hits.values()))
    return (c.book, '') if c.book is not None else (None, c.title)


def ask(llm, text, cands):
    """AI에게 후보 번호 하나를 묻는다. 고르지 않았거나(null) 목록 밖 번호면 None. AI 오류는 그대로 올린다(호출부가 다음에 다시)."""
    from intake.llm import complete_json
    from marketing.prompts import AD_BOOK_SYSTEM, build_ad_book_user
    raw = complete_json(llm, AD_BOOK_SYSTEM, build_ad_book_user(text, cands))
    n = raw.get('book') if isinstance(raw, dict) else None
    if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(cands):
        return cands[n - 1]
    return None


@dataclass
class Relinked:
    linked: int = 0    # 책이나 책 제목이 새로 정해진 광고
    asked: int = 0     # AI에게 물은 광고
    failed: int = 0    # AI 오류(다음에 다시 묻는다)
    changed: List[int] = field(default_factory=list)   # 바뀐 광고 pk


def relink(llm=None):
    """책이 빈 광고를 다시 맞춘다. 글자 맞추기는 매번(사이트에 새로 올라온 책·북펀드), AI는 광고마다 한 번(book_asked_at).
    글 내용을 못 읽은 광고는 건너뛴다. 글자 맞추기가 못 찾았다고 이미 정한 책 제목을 지우지는 않는다."""
    result = Relinked()
    todo = list(Ad.objects.filter(book__isnull=True).exclude(post_text=''))
    if not todo:
        return result
    cands = candidates()
    for ad in todo:
        book, title = match((ad.post_id, ad.ig_media_id), ad.post_text, cands)
        fields = []
        if book is None and not title and llm is not None and ad.book_asked_at is None:
            result.asked += 1
            try:
                picked = ask(llm, ad.post_text, cands)
            except Exception as e:   # 연결 오류·답 모양 오류: 글 내용은 로그에 남기지 않는다
                log.warning('ads book ask: %s', type(e).__name__)
                result.failed += 1
                continue
            ad.book_asked_at = timezone.now()
            fields.append('book_asked_at')
            if picked is not None:
                book, title = (picked.book, '') if picked.book is not None else (None, picked.title)
        if book is not None:
            ad.book, ad.book_title = book, ''
            fields += ['book', 'book_title']
        elif title and title != ad.book_title:
            ad.book_title = title
            fields.append('book_title')
        if 'book' in fields or 'book_title' in fields:
            result.linked += 1
            result.changed.append(ad.pk)
        if fields:
            ad.save(update_fields=fields + ['updated_at'])
    return result
