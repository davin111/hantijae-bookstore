"""오늘 현장·어제 현장 후기·중쇄 후보. 읽기만 하며 발송·used_at 변경은 주중 제안 흐름이 맡는다."""
from datetime import date, timedelta

from django.db.models import Q

from books.models import Book
from intake.models import WorkerState
from marketing.candidates import Candidate, KIND_LABEL
from marketing.models import BookProfile, Proposal, Signal
from marketing.moments import find_book
from marketing.text import similarity

REPRINT_DAYS = 14
PRIORITY = {'onsite_today': 6, 'onsite_after': 5, 'reprint': 3}


def _event(signal):
    """날짜·현장 여부·이름·장소. 새 플래그는 bool만, 없는 옛 행사만 보수적으로 추정한다."""
    d = signal.detail
    if signal.kind == Signal.MOMENT:
        event, day, legacy = d, signal.happens_on, d.get('type') == 'event'
        name = signal.title
    else:
        event = d.get('event') or {}
        if not isinstance(event, dict):
            return None
        try:
            day = date.fromisoformat(event.get('on') or '')
        except (ValueError, TypeError):
            return None
        legacy = d.get('category') == 'event'
        name = event.get('name') or signal.title
    place = event.get('place') or ''
    if 'onsite' in event:
        onsite = event['onsite'] is True
    else:
        onsite = legacy and '온라인' not in ' '.join([name, place, signal.title])
    if not day or not onsite:
        return None
    return {'date': day.isoformat(), 'name': name, 'place': place}


def _books(signal, quiet):
    """책 목록과 후보 허용 여부. 조용히 둔 책이 모두 빠진 신호는 책 없는 행사로 바꾸지 않는다."""
    d = signal.detail
    ids = set(d.get('book_ids' if signal.kind == Signal.MOMENT else 'books') or [])
    if signal.book_id:
        ids.add(signal.book_id)
    books = list(Book.objects.filter(pk__in=ids, is_published=True, visible=True).order_by('id'))
    if not ids and d.get('book_hint'):
        book = find_book(d['book_hint'])
        if book:
            ids.add(book.id)
            books = [book] if book.is_published and book.visible else []
    books = [b for b in books if b.id not in quiet]
    return books, not ids or bool(books)


def _sent(key, include_preview=True):
    sent = Proposal.objects.filter(candidate_key=key).filter(
        Q(briefing__sent_at__isnull=False) | Q(kind=Proposal.NOW, sent_at__isnull=False))
    return any(include_preview or not (p.extra or {}).get('content_preview_at')
               or (p.extra or {}).get('content_room_sent_at') for p in sent)


def _same(a, b):
    return (a.facts['date'] == b.facts['date']
            and (bool({book.id for book in a.books} & {book.id for book in b.books})
                 or similarity(a.facts['name'], b.facts['name']) >= 0.5))


def _items(today, now, reserved_ids=(), include_preview=True, check_sent=True):
    quiet = set(BookProfile.objects.filter(quiet_until__gte=today).values_list('book_id', flat=True))
    signals = list(Signal.objects.filter(Q(relevant=True) | Q(detail__status='cancelled'),
                                         kind__in=(Signal.MOMENT, Signal.SOCIAL))
                   .select_related('book').order_by('id'))
    # 대화에서 확인된 일을 먼저 두면 중복 SNS가 같은 행사에 붙는다.
    signals.sort(key=lambda s: (s.kind != Signal.MOMENT, s.id))
    events, reprints, blocked = [], [], set()
    for signal in signals:
        d = signal.detail
        books, allowed = _books(signal, quiet)
        if not allowed:
            continue
        cancelled = d.get('status') == 'cancelled' or (d.get('event') or {}).get('status') == 'cancelled'
        excluded = cancelled or signal.sensitive
        event = _event(signal)
        if event and event['date'] in (today.isoformat(), (today - timedelta(days=1)).isoformat()):
            kind = 'onsite_today' if event['date'] == today.isoformat() else 'onsite_after'
            promoted = kind == 'onsite_after' and (d.get('promoted') or (d.get('event') or {}).get('promoted'))
            stage = 'today' if kind == 'onsite_today' else 'after'
            candidate = Candidate(id=f'onsite:{signal.id}:{stage}', kind=kind, books=books,
                                  summary=f'{KIND_LABEL[kind]}: {event["name"]}'
                                          + (f' ({event["place"]})' if event['place'] else ''),
                                  facts=event, urgency=PRIORITY[kind], signal=signal)
            same = next((c for c in events if _same(c, candidate)), None)
            if same:
                same.more_signals.append(signal)
            else:
                events.append(candidate)
            if excluded or promoted:
                blocked.add(same.id if same else candidate.id)
        if (not excluded and signal.kind == Signal.MOMENT and d.get('type') == 'reprint' and books
                and d.get('status') in ('confirmed', 'done')
                and (signal.happens_on is None or signal.happens_on <= today)
                and (signal.used_at is None or signal.id in reserved_ids) and not d.get('promoted')
                and now - timedelta(days=REPRINT_DAYS) <= signal.found_at <= now):
            reprints.append(Candidate(id=f'reprint:{signal.id}', kind='reprint', books=books,
                                      summary=f'중쇄 소식: {signal.title} ― {d.get("summary", "")}'.rstrip(' ―'),
                                      facts={'printing': d.get('printing', ''),
                                             'date': signal.happens_on.isoformat() if signal.happens_on else ''},
                                      urgency=PRIORITY['reprint'], signal=signal))
    out = []
    for candidate in events + reprints:
        keys = [candidate.id]
        if candidate.kind.startswith('onsite_'):
            stage = 'today' if candidate.kind == 'onsite_today' else 'after'
            keys += [f'onsite:{s.id}:{stage}' for s in candidate.more_signals]
        if candidate.id not in blocked and (not check_sent or not any(_sent(key, include_preview) for key in keys)):
            out.append(candidate)
    return sorted(out, key=lambda c: (-c.urgency, c.facts.get('date') or '', c.signal.id))


def items(today, now, reserved_ids=(), include_preview=True):
    """스위치가 켜졌을 때만 날짜 후보. 받는 곳(target)은 호출자가 확인한다."""
    return _items(today, now, reserved_ids, include_preview) if WorkerState.get('dated_mode', 'off') == 'live' else []


def fallback(candidate):
    """오늘 알림이 생성·검증 과정에서 빠져도 알려 줄 사실 한 줄. 후기는 대신 지어내지 않는다."""
    if candidate.kind != 'onsite_today':
        return None
    return {'channel': 'instagram', 'title': '',
            'body': f'오늘 {candidate.facts["name"]} 현장입니다.\n#한티재의책'}


def monday_line(today, now):
    if today.weekday() != 0:
        return ''
    events = [c for c in items(today, now) if c.kind == 'onsite_today']
    if not events:
        return ''
    names = ' · '.join(c.facts['name'] + (f'({c.facts["place"]})' if c.facts['place'] else '') for c in events)
    return f'오늘 {names} 현장 일정이 있어요. 현장 사진 한 장과 두 줄이면 충분해요. 사람 얼굴이 나오면 먼저 허락받아 주세요.'


def preview(today, now, days=7):
    """끄고도 볼 수 있는 읽기 전용 예상 목록. 한 번 나갈 중쇄를 매일 되풀이해 표시하지 않는다."""
    lines = [f"dated_mode={WorkerState.get('dated_mode', 'off')} · 앞으로 {days}일 미리보기"]
    seen = set()
    for offset in range(days):
        day = today + timedelta(days=offset)
        rows = _items(day, now + timedelta(days=offset))
        labels = []
        for candidate in rows:
            if candidate.id in seen:
                continue
            if day.weekday() == 0:
                if candidate.kind != 'onsite_today':
                    continue
                label = '월요일 브리핑 · ' + candidate.summary
            else:
                label = candidate.summary
            labels.append(label)
            seen.add(candidate.id)
        lines.append(f'{day.month}/{day.day} · ' + (' / '.join(labels) if labels else '날짜 후보 없음'))
    return '\n'.join(lines)
