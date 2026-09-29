"""주간 브리핑 후보. 규칙만으로 만들고(LLM 없음), 고르기는 briefing.py가 LLM에 맡긴다."""
import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional

from django.db.models import Max, Q

from books.models import Book
from intake.models import WorkerState
from marketing.funding import ends_on, is_stalled, live_campaigns
from marketing.hooks import upcoming
from marketing.kit import blog_has
from marketing.models import BookProfile, Proposal, SalesSnapshot, Signal
from marketing.moments import TYPE_LABEL, find_book, seen_on
from marketing.sales import latest
from marketing.text import title_key, won_display
from marketing.timeutil import kst_today, week_start

KIND_LABEL = {'hook': '기념일', 'fund': '진행 중 펀딩', 'news': '저자 소식', 'surge': '판매 지수 급등',
              'blog': '블로그 글 없음', 'noreview': '리뷰 없음', 'moment': '대화 속 계기'}
# 판매 지수 급등의 원인 가설로 붙일 만한 대화 속 계기
ROOM_TALK_TYPES = ('group', 'stock', 'author', 'media', 'issue', 'selection')
# 새 계기가 없는 후보는 같은 책을 3주 안에 다시 제안하지 않는다
NEEDS_REST = ('blog', 'noreview', 'surge')


@dataclass
class Candidate:
    id: str
    kind: str
    books: List[Book]
    summary: str
    facts: Dict[str, Any]
    urgency: int
    memorial: bool = False
    signal: Optional[Signal] = field(default=None, repr=False)

    def as_prompt(self):
        return {'id': self.id, 'kind': KIND_LABEL[self.kind], 'memorial': self.memorial,
                'books': [f'『{b.title}』 {b.subtitle}'.strip() for b in self.books],
                'summary': self.summary, 'facts': self.facts}

    def allowed_texts(self):
        texts = [self.summary, json.dumps(self.facts, ensure_ascii=False)]
        for b in self.books:
            texts += [b.title, b.subtitle or '', b.description or '', b.short_description or '']
        return texts


def _live(books):
    return [b for b in books if b.is_published and b.visible]


def hook_candidates(today, days=21):
    out = []
    for hook, on in upcoming(today, days):
        books = _live(hook.books.all())
        if not books:
            continue
        left = (on - today).days
        out.append(Candidate(id=f'hook:{hook.id}:{on.isoformat()}', kind='hook', books=books,
                             summary=f'{on.month}월 {on.day}일 {hook.name}' + (f' ({hook.note})' if hook.note else ''),
                             facts={'date': on.isoformat(), 'days_left': left},
                             urgency=3 if left <= 7 else 2, memorial=hook.memorial))
    return out


def _book_for_campaign(camp):
    key = title_key(camp.title)
    for book in Book.objects.filter(is_published=True).order_by('-published_date')[:30]:
        if title_key(book.title) and title_key(book.title) in key:
            return book
    return None


def funding_candidates(today, now):
    out = []
    for camp in live_campaigns(now):
        end = ends_on(camp)
        left = (end - today).days
        summary = f'{camp.title} 펀딩 ― {end.month}월 {end.day}일 마감'
        facts = {'ends_on': end.isoformat(), 'days_left': left}
        snap = camp.snapshots.order_by('-date').first()
        if snap:
            summary += f', 목표의 {snap.percent}%({won_display(snap.amount)}, {snap.books}권)'
            facts.update({'amount': won_display(snap.amount), 'percent': snap.percent, 'books': snap.books})
        stalled = is_stalled(camp, today)
        if stalled:
            summary += ', 최근 3일 동안 거의 늘지 않음'
            facts['stalled'] = True
        book = _book_for_campaign(camp)
        out.append(Candidate(id=f'fund:{camp.id}', kind='fund', books=[book] if book else [], summary=summary,
                             facts=facts, urgency=3 if (left <= 7 or stalled) else 2))
    return out


def news_candidates(now, days=14):
    out = []
    # 이번 주 브리핑이 이미 쓴 소식은 다시 만들 때 또 후보가 된다(save_briefing이 옛 항목을 지우며 풀어 준다)
    unused = Q(used_at__isnull=True) | Q(proposal__briefing__week_start=week_start(kst_today(now)))
    qs = (Signal.objects.filter(unused, kind=Signal.NEWS, relevant=True, sensitive=False,
                                found_at__gte=now - timedelta(days=days), book__isnull=False)
          .select_related('book').distinct())
    for s in qs:
        d = s.happens_on
        when = f'{d.month}월 {d.day}일 ' if d else ''
        out.append(Candidate(id=f'news:{s.id}', kind='news', books=[s.book],
                             summary=f'{when}〈{s.detail.get("source", "")}〉 「{s.title}」 ― {s.detail.get("summary", "")}',
                             facts={'date': d.isoformat() if d else '', 'url': s.url}, urgency=2, signal=s))
    return out


def moment_books(s):
    """계기의 책들. 책을 못 찾았던 계기(book_hint)는 그사이 DB에 들어온 책과 다시 맞춰 보고, 맞으면 저장한다."""
    ids = s.detail.get('book_ids') or ([s.book_id] if s.book_id else [])
    by_id = {b.id: b for b in Book.objects.filter(id__in=ids)}
    books = [by_id[i] for i in ids if i in by_id]
    if not books and s.detail.get('book_hint'):
        b = find_book(s.detail['book_hint'])
        if b:
            s.book, s.detail = b, {**s.detail, 'book_ids': [b.id], 'book_hint': ''}
            s.save(update_fields=['book', 'detail'])
            books = [b]
    return books


def moment_candidates(today, now):
    """대화 속 계기. 앞으로 21일 안, 끝난 지 7일 안(후기), 날짜 없이 14일(신간 예고 30일) 안에 찾은 것."""
    out = []
    unused = Q(used_at__isnull=True) | Q(proposal__briefing__week_start=week_start(today))
    qs = Signal.objects.filter(unused, kind=Signal.MOMENT, relevant=True, sensitive=False).distinct().order_by('id')
    for s in qs:
        d = s.detail
        if d.get('status') == 'cancelled' or d.get('promoted'):
            continue
        day, left = s.happens_on, None
        if day:
            left = (day - today).days
            if not -7 <= left <= 21:
                continue
        elif seen_on(s) < today - timedelta(days=30 if d.get('type') == 'upcoming' else 14):
            continue
        books = moment_books(s)
        if not books:
            continue
        label = TYPE_LABEL.get(d.get('type'), '계기')
        when = f'{day.month}월 {day.day}일 ' if day else ''
        summary = f'{when}{label}: {s.title} ― {d.get("summary", "")}'.rstrip(' ―')
        if d.get('date_unverified'):
            summary += f' (날짜 확인 필요: {d.get("date_text", "")})'
        if left is not None and left < 0:
            summary += ' (끝난 일 — 후기 글 후보)'
        out.append(Candidate(id=f'moment:{s.id}', kind='moment', books=books, summary=summary,
                             facts={'date': day.isoformat() if day else '', 'type': label, 'status': d.get('status', ''),
                                    'place': d.get('place', ''), 'days_left': left},
                             urgency=3 if left is not None and 0 <= left <= 7 else 2, signal=s))
    return out


def with_moments(cands, moments, now):
    """겹침 정리: 진행 중 펀딩·선정 소식과 같은 책의 계기는 빼고, 급등 후보에는 같은 책 계기를 원인 가설로 붙인다."""
    fund_books = {b.id for c in cands if c.kind == 'fund' for b in c.books}
    selected = set(Signal.objects.filter(kind='selection', book__isnull=False, found_at__gte=now - timedelta(days=30))
                   .values_list('book_id', flat=True))
    keep = []
    for m in moments:
        kind, ids = m.signal.detail.get('type'), {b.id for b in m.books}
        if (kind == 'funding' and ids & fund_books) or (kind == 'selection' and ids & selected):
            continue
        keep.append(m)
    for surge in [c for c in cands if c.kind == 'surge' and c.signal is None]:
        book_id = surge.books[0].id
        talk = next((m for m in keep if m.signal.detail.get('type') in ROOM_TALK_TYPES
                     and book_id in {b.id for b in m.books}
                     and seen_on(m.signal) >= kst_today(now) - timedelta(days=14)), None)
        if talk:
            surge.summary += f' ― 방에서 나온 이야기: {talk.signal.title}'
            surge.facts['room'] = talk.signal.title
            surge.signal = talk.signal
            keep.remove(talk)
    return cands + keep


def surge_candidates(today):
    last = SalesSnapshot.objects.filter(date__lte=today).aggregate(d=Max('date'))['d']
    if not last:
        return []
    out = []
    for snap in SalesSnapshot.objects.filter(date=last).select_related('book'):
        before = latest(snap.book, last - timedelta(days=7))
        if before and snap.sales_point - before.sales_point >= 100 and snap.sales_point >= before.sales_point * 1.5:
            out.append(Candidate(id=f'surge:{snap.book_id}:{last.isoformat()}', kind='surge', books=[snap.book],
                                 summary=f'판매 지수가 일주일 새 {before.sales_point}에서 {snap.sales_point}로 올랐음',
                                 facts={'before': before.sales_point, 'after': snap.sales_point}, urgency=2))
    return out


def blog_gap_candidates(today, posts, days=180):
    if posts is None:  # 블로그 RSS를 못 읽었다 → 모든 책을 '글 없음'으로 오판하지 않게 만들지 않는다
        return []
    out = []
    for book in Book.objects.filter(is_published=True, visible=True, published_date__gte=today - timedelta(days=days),
                                    published_date__lte=today):
        if not blog_has(book, posts):
            d = book.published_date
            out.append(Candidate(id=f'blog:{book.id}', kind='blog', books=[book],
                                 summary=f'{d.month}월 {d.day}일에 나왔는데 블로그 글이 아직 없음',
                                 facts={'published': d.isoformat()}, urgency=1))
    return out


def noreview_candidates(today):
    out = []
    for book in Book.objects.filter(is_published=True, visible=True, published_date__lte=today - timedelta(days=30),
                                    published_date__gte=today - timedelta(days=365)):
        snap = latest(book, today)
        if snap and snap.short_reviews == 0 and snap.reviews == 0:
            out.append(Candidate(id=f'noreview:{book.id}', kind='noreview', books=[book],
                                 summary='알라딘 리뷰와 100자평이 아직 없음', facts={'sales_point': snap.sales_point},
                                 urgency=1))
    return out


def _recently_proposed(today, now):
    """3주 쉬기에 세는 책: 실제로 보낸 지난 브리핑의 항목만. 이번 주 브리핑은 다시 만들 때 자기 항목에 걸리지 않게 뺀다."""
    return set(Proposal.objects.filter(kind=Proposal.BRIEF_ITEM, created_at__gte=now - timedelta(days=21),
                                       briefing__sent_at__isnull=False)
               .exclude(briefing__week_start=week_start(today)).values_list('book_id', flat=True))


def select(cands, today, now, limit=12):
    quiet = set(BookProfile.objects.filter(quiet_until__gte=today).values_list('book_id', flat=True))
    recent = _recently_proposed(today, now)
    out = []
    for c in cands:
        had_books = bool(c.books)
        c.books = [b for b in c.books if b.id not in quiet]
        if not c.books and (had_books or c.kind != 'fund'):  # 책이 모두 쉬는 중이면 펀딩이라도 뺀다
            continue
        if c.kind in NEEDS_REST and any(b.id in recent for b in c.books):
            continue
        out.append(c)
    out.sort(key=lambda c: -c.urgency)
    return out[:limit]


def gather(today, now, posts):
    cands = (hook_candidates(today) + funding_candidates(today, now) + news_candidates(now) + surge_candidates(today)
             + blog_gap_candidates(today, posts) + noreview_candidates(today))
    if WorkerState.get('moment_mode', 'off') == 'live':
        cands = with_moments(cands, moment_candidates(today, now), now)
    return select(cands, today, now)
