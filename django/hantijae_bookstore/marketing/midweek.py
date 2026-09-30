"""주중 제안: 다음 월요일 브리핑보다 날짜가 먼저 오는 대화 속 계기와 기념일(2일 전~당일)을 화~토에 한 메시지로 보낸다.

기념일도 넣는 이유(다른 세션 제안, 2026-09-30): 브리핑은 4개만 고르므로 월요일 브리핑이 고르지 않은 기념일은
다시 오지 않는다. 스위치(midweek_mode)를 계기 잡기(moment_mode)와 따로 둬 기념일만 먼저 켤 수 있다.
"""
from datetime import date, datetime, time, timedelta

from django.db.models import Q

from intake.models import TelegramChat, WorkerState
from marketing import candidates as C
from marketing.briefing import compose
from marketing.models import BookProfile, Draft, Proposal, Signal
from marketing.timeutil import KST, week_start

BUILD_DAYS = (1, 2, 3, 4, 5)  # 화~토
HOOK_DAYS, MAX_ITEMS = 2, 3


def modes():
    return WorkerState.get('midweek_mode', 'off'), WorkerState.get('moment_mode', 'off')


def to_room(marketing_mode):
    return modes()[0] == 'live' and marketing_mode == 'live'


def target(host, marketing_mode):
    """받는 곳: live(마케팅도 live)면 검수 방, admin_only·live(마케팅이 live가 아님)면 관리자 1:1, off면 없음."""
    mw, _ = modes()
    if mw == 'off':
        return None
    return host.review_chat_id() if to_room(marketing_mode) else host._chat(TelegramChat.ADMIN)


def _next_monday(today):
    return week_start(today) + timedelta(days=7)


def moment_items(today, now):
    """확인된 날짜가 오늘 ~ 다음 월요일 사이인, 아직 쓰지 않은 대화 속 계기(신간 예고·끝난 일 제외)."""
    out = []
    for c in C.moment_candidates(today, now):
        s = c.signal
        if s.used_at or s.detail.get('type') == 'upcoming' or s.detail.get('status') == 'done':
            continue
        if not s.happens_on or not today <= s.happens_on <= _next_monday(today):
            continue
        out.append(c)
    return out


def _sent(key):
    """보낸 브리핑(미리보기만 한 것은 아님)이나 보낸 주중 제안이 이미 쓴 후보인가."""
    return Proposal.objects.filter(candidate_key=key).filter(
        Q(briefing__sent_at__isnull=False) | Q(kind=Proposal.NOW, sent_at__isnull=False)).exists()


def hook_items(today):
    """2일 안(당일 포함)의 기념일 가운데 다음 월요일 전이고, 보낸 브리핑·주중 제안이 쓰지 않은 것."""
    return [c for c in C.hook_candidates(today, days=HOOK_DAYS)
            if date.fromisoformat(c.facts['date']) < _next_monday(today) and not _sent(c.id)]


def _without_quiet(cands, today):
    quiet = set(BookProfile.objects.filter(quiet_until__gte=today).values_list('book_id', flat=True))
    out = []
    for c in cands:
        c.books = [b for b in c.books if b.id not in quiet]
        if c.books:
            out.append(c)
    return out


def _day_start(today):
    return datetime.combine(today, time.min, tzinfo=KST)


def release_stale(today):
    """오늘 전에 만들고 못 보낸 주중 제안을 지우고, 그 계기를 다시 후보가 되게 풀어 준다."""
    stale = Proposal.objects.filter(kind=Proposal.NOW, sent_at__isnull=True, created_at__lt=_day_start(today))
    Signal.objects.filter(proposal__in=stale).update(used_at=None)
    stale.delete()


def build(llm, today, now, marketing_mode):
    """(만든 제안들, 버린 이유들). 화~토, midweek_mode가 off가 아닐 때, 하루 한 번."""
    release_stale(today)
    mw, mm = modes()
    if mw == 'off' or today.weekday() not in BUILD_DAYS:
        return [], []
    if Proposal.objects.filter(kind=Proposal.NOW, created_at__gte=_day_start(today)).exists():
        return [], []
    cands = hook_items(today)
    if mm == 'live' or (mm == 'admin_only' and not to_room(marketing_mode)):
        cands += moment_items(today, now)
    cands = sorted(_without_quiet(cands, today), key=lambda c: (c.facts.get('date') or '', c.id))[:MAX_ITEMS]
    if not cands:
        return [], []
    items, dropped = compose(llm, cands, today, midweek=True)
    made = []
    for rank, (cand, headline, reason, d) in enumerate(items, 1):
        p = Proposal.objects.create(kind=Proposal.NOW, book=cand.books[0], signal=cand.signal, candidate_key=cand.id,
                                    headline=headline[:300], reason=reason, rank=rank)
        Draft.objects.create(proposal=p, channel=d['channel'], title=d['title'][:300], body=d['body'])
        if cand.signal:
            Signal.objects.filter(pk=cand.signal.pk).update(used_at=now)
        made.append(p)
    return made, dropped
