"""주간 브리핑 후보. 규칙만으로 만들고(LLM 없음), 고르기는 briefing.py가 LLM에 맡긴다."""
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from django.db.models import Max, Q

from books.models import Book
from marketing import meta
from marketing.funding import ends_on, is_stalled, live_campaigns
from marketing.hooks import upcoming
from marketing.kit import blog_has
from marketing.models import BookProfile, Proposal, SalesSnapshot, Signal
from marketing.sales import latest
from marketing.text import loose_key, similarity, title_key, won_display
from marketing.timeutil import kst_today, week_start
from web.models import Notice

KIND_LABEL = {'hook': '기념일', 'fund': '진행 중 펀딩', 'news': '저자 소식', 'surge': '판매 지수 급등',
              'blog': '블로그 글 없음', 'noreview': '리뷰 없음', 'selection': '공공 선정',
              'sns_event': '다가오는 행사', 'sns_after': '행사 후기', 'sns_repost': '공식 채널로 옮겨 싣기',
              'sns_press': '서평·기사 모음'}
# 새 계기가 없는 후보는 같은 책을 3주 안에 다시 제안하지 않는다
NEEDS_REST = ('blog', 'noreview', 'surge')
# 책 없이도 브리핑에 올릴 수 있는 후보(사이트에 아직 없는 신간·행사, 펀딩)
SNS_KINDS = ('sns_event', 'sns_after', 'sns_repost', 'sns_press')
BOOKLESS_OK = ('fund',) + SNS_KINDS


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
    more_signals: List[Signal] = field(default_factory=list, repr=False)  # 한 후보가 여러 신호를 묶을 때 나머지

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


def selection_candidates(now, days=14):
    """새로 확인한 공공 선정(철회·옛 발표 제외) 중 첫 화면 알림이 실제로 떠 있는 것만 후보로 올린다.
    제목만 맞은 것(알림이 아직 미리보기)이나 운영진이 내린 알림은 확정된 선정처럼 브리핑에 보이면 안 된다."""
    unused = Q(used_at__isnull=True) | Q(proposal__briefing__week_start=week_start(kst_today(now)))
    qs = (Signal.objects.filter(unused, kind=Signal.SELECTION, relevant=True, found_at__gte=now - timedelta(days=days),
                                book__isnull=False).select_related('book').distinct())
    notice_ids = [s.detail.get('notice_id') for s in qs if s.detail.get('notice_id')]
    posted_ids = set(Notice.objects.filter(id__in=notice_ids, state=Notice.POSTED).values_list('id', flat=True))
    out = []
    for s in qs:
        if s.detail.get('notice_id') not in posted_ids:
            continue
        out.append(Candidate(id=f'selection:{s.id}', kind='selection', books=[s.book],
                             summary=f'{s.title} 선정 ― 첫 화면 알림이 떠 있음',
                             facts={'url': s.url, 'date': s.happens_on.isoformat() if s.happens_on else ''},
                             urgency=3, signal=s))
    return out


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
        if not c.books and (had_books or c.kind not in BOOKLESS_OK):  # 책이 모두 쉬는 중이면 책 없어도 되는 후보라도 뺀다
            continue
        if c.kind in NEEDS_REST and any(b.id in recent for b in c.books):
            continue
        out.append(c)
    out.sort(key=lambda c: -c.urgency)
    return out[:limit]


# ---- 운영진 개인 SNS(marketing.social·social_judge가 만든 Signal(kind=social)) ----

SNS_UPCOMING_DAYS, SNS_AFTER_DAYS, SNS_FOUND_DAYS, SNS_PRESS_MAX = 21, 10, 14, 5
PRESS_CATEGORIES = ('review', 'press', 'author_news')
CHANNEL_LABEL = {'blog': '블로그', 'instagram': '인스타', 'facebook': '페이스북 페이지'}
PLATFORM_LABEL = {'facebook': '페이스북', 'instagram': '인스타'}


def _sns_signals(today, now):
    """아직 안 쓴(이번 주 브리핑이 쓴 것은 다시 후보) 관련 신호 가운데 14일 안에 찾았거나 행사가 21일 안인 것."""
    ws = week_start(kst_today(now))
    this_week = [i for extra in Proposal.objects.filter(briefing__week_start=ws).values_list('extra', flat=True)
                 for i in (extra or {}).get('signals', [])]
    unused = Q(used_at__isnull=True) | Q(proposal__briefing__week_start=ws) | Q(pk__in=this_week)
    recent = (Q(found_at__gte=now - timedelta(days=SNS_FOUND_DAYS))
              | Q(happens_on__gte=today, happens_on__lte=today + timedelta(days=SNS_UPCOMING_DAYS)))
    return list(Signal.objects.filter(unused, recent, kind=Signal.SOCIAL, relevant=True, sensitive=False)
                .select_related('book').distinct().order_by('happens_on', 'id'))


def sns_where(s):
    who = '·'.join(s.detail.get('who') or [])
    where = '·'.join(PLATFORM_LABEL.get(p, p) for p in s.detail.get('platforms') or [])
    return f'{who}님 개인 {where}'


def _needles(s):
    names = list(s.detail.get('titles') or [])
    names += list(Book.objects.filter(pk__in=s.detail.get('books') or []).values_list('title', flat=True))
    names.append((s.detail.get('event') or {}).get('name', ''))
    return [k for k in (loose_key(n) for n in names) if len(k) >= 4]


def official_status(s, blog, meta_posts):
    """공식 채널마다 True(이미 있음)·False(없음)·None(못 읽음). 못 읽은 채널을 '없다'고 하지 않는다."""
    try:
        since = date.fromisoformat(s.detail.get('posted_on', '')) - timedelta(days=3)
    except ValueError:
        since = kst_today(s.found_at) - timedelta(days=3)
    needles = _needles(s)
    mine = list(s.social_posts.exclude(text='').values_list('text', flat=True))

    def hit(text, day):
        if day is not None and day < since:
            return False
        key = loose_key(text)
        return any(n in key for n in needles) or any(similarity(text, m) >= 0.6 for m in mine)

    out = {'blog': None if blog is None else any(hit(p.title, getattr(p, 'date', None)) for p in blog)}
    for ch in ('instagram', 'facebook'):
        rows = meta_posts.get(ch)
        out[ch] = None if rows is None else any(hit(r.text, kst_today(r.posted_at)) for r in rows)
    return out


def _official_note(status):
    no = [CHANNEL_LABEL[c] for c, v in status.items() if v is False]
    unknown = [CHANNEL_LABEL[c] for c, v in status.items() if v is None]
    parts = ([f'공식 {"·".join(no)}엔 아직 없음'] if no else []) + ([f'확인 못 한 곳: {"·".join(unknown)}'] if unknown else [])
    return ', '.join(parts)


def social_candidates(today, now, posts, fetch=None):
    """운영진 개인 SNS 신호 → 다가오는 행사·행사 후기·공식 채널로 옮겨 싣기·서평·기사 모음.
    공식 채널(Meta)은 신호가 있을 때만 읽는다. posts는 블로그 글(못 읽었으면 None)."""
    signals = _sns_signals(today, now)
    if not signals:
        return []
    meta_posts = None
    out, press = [], []
    for s in signals:
        d = s.detail
        books = _live(Book.objects.filter(pk__in=d.get('books') or []))
        facts = {'who': sns_where(s), 'url': s.url, 'posted': d.get('posted_on', '')}
        if d.get('titles'):
            facts['not_on_site'] = d['titles']
        if d.get('category') in PRESS_CATEGORIES:
            press.append((s, books))
            continue
        if meta_posts is None:
            meta_posts = (fetch or meta.official_posts)(now - timedelta(days=45))
        status = official_status(s, posts, meta_posts)
        facts['official'] = {CHANNEL_LABEL[c]: {True: '있음', False: '없음', None: '모름'}[v] for c, v in status.items()}
        note = _official_note(status)
        ev = d.get('event') or {}
        on = date.fromisoformat(ev['on']) if ev.get('on') else None
        name = ev.get('name') or '행사'
        if on and today <= on <= today + timedelta(days=SNS_UPCOMING_DAYS):
            left = (on - today).days
            place = f'({ev["place"]})' if ev.get('place') else ''
            out.append(Candidate(id=f'sns:{s.id}', kind='sns_event', books=books,
                                 summary=f'{on.month}월 {on.day}일 {name}{place} ― {sns_where(s)}에 안내가 있음'
                                         + (f', {note}' if note else ''),
                                 facts={**facts, 'date': on.isoformat(), 'days_left': left},
                                 urgency=3 if left <= 7 else 2, signal=s))
        elif on and today - timedelta(days=SNS_AFTER_DAYS) <= on < today:
            out.append(Candidate(id=f'sns:{s.id}', kind='sns_after', books=books,
                                 summary=f'지난 {on.month}월 {on.day}일 {name} ― 후기를 공식 채널에 올릴 수 있음',
                                 facts={**facts, 'date': on.isoformat()}, urgency=1, signal=s))
        elif not on and not all(v is True for v in status.values()):
            out.append(Candidate(id=f'sns:{s.id}', kind='sns_repost', books=books,
                                 summary=f'{d.get("summary", "")} ― {sns_where(s)}에 올린 글' + (f', {note}' if note else ''),
                                 facts=facts, urgency=2, signal=s))
    if press:
        picked = press[:SNS_PRESS_MAX]
        books = []
        for _, bs in picked:
            books += [b for b in bs if b not in books]
        items = [{'summary': s.detail.get('summary', ''), 'url': s.url,
                  'source': (s.detail.get('link') or {}).get('source', '')} for s, _ in picked]
        out.append(Candidate(id=f'sns_press:{week_start(today).isoformat()}', kind='sns_press', books=books,
                             summary='운영진이 최근 공유한 서평·기사 ― ' + ' / '.join(i['summary'] for i in items),
                             facts={'items': items}, urgency=1, signal=picked[0][0],
                             more_signals=[s for s, _ in picked[1:]]))
    return out


def merge_fund_posts(funds, sns):
    """진행 중 펀딩 후보가 있는 책의 운영진 펀딩 글은 따로 후보로 만들지 않고 그 펀딩 후보에 적는다."""
    out = []
    for c in sns:
        if c.kind == 'sns_repost' and c.signal.detail.get('category') == 'funding':
            titles = [loose_key(t) for t in c.signal.detail.get('titles') or [] if len(loose_key(t)) >= 4]
            fund = next((f for f in funds if set(f.books) & set(c.books)
                         or any(t in loose_key(f.summary) for t in titles)), None)
            if fund:
                fund.facts.setdefault('personal_posts', []).append(
                    f'{c.signal.detail.get("posted_on", "")} {sns_where(c.signal)}')
                continue
        out.append(c)
    return out


def social_context(now, days=SNS_FOUND_DAYS, limit=15):
    """브리핑 LLM에 참고로 줄 최근 운영진 SNS 소식(후보 아님): 이미 쓴 것·공식 채널에 있는 것도 포함."""
    qs = (Signal.objects.filter(kind=Signal.SOCIAL, relevant=True, sensitive=False,
                                found_at__gte=now - timedelta(days=days)).order_by('found_at', 'id')[:limit])
    return [f'{s.detail.get("posted_on", "")} {sns_where(s)}: {s.detail.get("summary", "")}' for s in qs]


def gather(today, now, posts):
    funds = funding_candidates(today, now)
    sns = merge_fund_posts(funds, social_candidates(today, now, posts))
    cands = (hook_candidates(today) + funds + news_candidates(now) + selection_candidates(now) + sns
             + surge_candidates(today) + blog_gap_candidates(today, posts) + noreview_candidates(today))
    return select(cands, today, now)
