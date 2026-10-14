"""주중 제안: 다음 월요일 브리핑보다 날짜가 먼저 오는 대화 속 계기와 기념일(2일 전~당일)을 화~토에 한 메시지로 보낸다.

기념일도 넣는 이유(다른 세션 제안, 2026-09-30): 브리핑은 4개만 고르므로 월요일 브리핑이 고르지 않은 기념일은
다시 오지 않는다. 스위치(midweek_mode)를 계기 잡기(moment_mode)와 따로 둬 기념일만 먼저 켤 수 있다.
"""
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Q

from intake.models import TelegramChat, WorkerState
from marketing import candidates as C
from marketing.briefing import compose
from marketing.models import BookProfile, Draft, Proposal, Signal
from marketing.timeutil import KST, week_start

BUILD_DAYS = (1, 2, 3, 4, 5)  # 화~토
HOOK_DAYS, MAX_ITEMS = 2, 3


def build_day(today):
    return today.weekday() in BUILD_DAYS or (today.weekday() == 6 and WorkerState.get('dated_mode') == 'live')


def send_at(today):
    onsite = (WorkerState.get('dated_mode') == 'live' and Proposal.objects.filter(
        kind=Proposal.NOW, created_at__gte=_day_start(today),
        candidate_key__startswith='onsite:', candidate_key__endswith=':today')
        .filter(Q(sent_at__isnull=True) | Q(extra__has_key='content_preview_at'))
        .exclude(extra__has_key='content_room_sent_at').exists())
    return (8, 30) if onsite else (9, 30)


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
        had_books = bool(c.books)
        c.books = [b for b in c.books if b.id not in quiet]
        if c.books or (not had_books and c.kind in C.BOOKLESS_OK):
            out.append(c)
    return out


def _day_start(today):
    return datetime.combine(today, time.min, tzinfo=KST)


def release_stale(today):
    """오늘 전에 만들고 못 보낸 주중 제안을 지우고, 그 계기를 다시 후보가 되게 풀어 준다."""
    period = f'editor:{today:%Y-%m}:{1 if today.day <= 15 else 2}'
    stale = Proposal.objects.filter(kind=Proposal.NOW, sent_at__isnull=True,
                                    created_at__lt=_day_start(today)).exclude(candidate_key=period)
    more = [pk for extra in stale.values_list('extra', flat=True)
            for pk in (extra or {}).get('more_signal_ids', []) if type(pk) is int]
    Signal.objects.filter(Q(proposal__in=stale) | Q(pk__in=more)).update(used_at=None)
    stale.delete()


def build(llm, today, now, marketing_mode, posts=None):
    """날짜 후보·편집 질문을 기존 한 메시지에 합친다. 일요일은 날짜 후보만 다룬다."""
    from marketing import dated, editor, peers, series
    release_stale(today)
    mw, mm = modes()
    if mw == 'off' or not build_day(today):
        return [], []
    if Proposal.objects.filter(kind=Proposal.NOW, created_at__gte=_day_start(today)).exists():
        return [], []
    cands = dated.items(today, now)
    diary = None
    if today.weekday() in BUILD_DAYS:
        dated_signals = {c.signal.id for c in cands if c.signal}
        cands += hook_items(today)
        cands += peers.candidate_items(today, now)
        cands += series.items(today, now)
        if mm == 'live' or (mm == 'admin_only' and not to_room(marketing_mode)):
            cands += [c for c in moment_items(today, now) if c.signal.id not in dated_signals]
        diary = editor.prepare(today, posts, llm, now)
        if diary:
            cands.append(diary[0])
    priority = {'onsite_today': 0, 'onsite_after': 1, 'editor': 2, 'reprint': 3}
    cands = sorted(_without_quiet(cands, today),
                   key=lambda c: (priority.get(c.kind, 4), c.facts.get('date') or '', c.id))[:MAX_ITEMS]
    if diary and diary[0] not in cands:
        editor.defer(today, '오늘 제안 세 항목이 차서 다음 제안일에 다시 확인', now)
    if not cands:
        return [], []
    regular = [c for c in cands if c.kind != 'editor']
    items, dropped = compose(llm, regular, today, midweek=True) if regular else ([], [])
    for c in cands:
        if c.kind == 'editor':
            items.append((c, '이번 「편집 일기」 — 질문 세 개 준비했어요',
                          '생각나는 질문에 짧게 답해 주세요. 답하신 내용만 글로 다듬어요.', diary[1]))
        elif c.kind == 'onsite_today' and not any(i[0].id == c.id for i in items):
            items.append((c, c.summary, '현장 사진 한 장과 두 줄이면 충분해요. 사람 사진은 허락을 받아 주세요.',
                          dated.fallback(c)))
    order = {c.id: i for i, c in enumerate(cands)}
    items.sort(key=lambda i: order[i[0].id])
    made = []
    with transaction.atomic():
        for rank, (cand, headline, reason, d) in enumerate(items[:MAX_ITEMS], 1):
            source_urls = list(dict.fromkeys(cand.link.splitlines() + cand.facts.get('source_urls', [])))
            p = Proposal.objects.create(kind=Proposal.NOW, book=cand.books[0] if cand.books else None,
                                        signal=cand.signal, candidate_key=cand.id, headline=headline[:300],
                                        reason=reason, rank=rank, extra={'candidate_kind': cand.kind, 'memorial': cand.memorial,
                                            'book_ids': [b.pk for b in cand.books],
                                            'link': source_urls[0] if source_urls else '',
                                            'link_label': C.LINK_LABEL.get(cand.kind, '원문'),
                                            'source_urls': source_urls,
                                            'more_signal_ids': [s.id for s in cand.more_signals]})
            extra = dict(d.get('extra') or {})
            if d.get('places'):
                extra['places'] = d['places']
            Draft.objects.create(proposal=p, channel=d['channel'], title=d.get('title', '')[:300], body=d['body'], extra=extra)
            if cand.signal and cand.kind != 'onsite_today':
                Signal.objects.filter(pk__in=[cand.signal.pk] + [s.pk for s in cand.more_signals]).update(used_at=now)
            if cand.kind == 'editor':
                editor.mark_generated(p, now)
            made.append(p)
    return made, dropped
