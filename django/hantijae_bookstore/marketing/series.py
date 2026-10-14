"""확인된 소식과 계기로만 만드는 금요일 네이버 블로그 연재 후보. 생성과 발송은 별개다."""
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.db.models import Q

from books.models import Book
from intake.models import WorkerState
from marketing.candidates import Candidate
from marketing.hooks import upcoming
from marketing.models import BookProfile, Draft, Proposal, Signal
from marketing.moments import find_book
from marketing.text import loose_key
from marketing.timeutil import kst_today, week_start

ANCHOR = date(2026, 10, 5)
SIGNAL_KINDS = (Signal.NEWS, Signal.SELECTION, Signal.MOMENT)
MOMENT_KINDS = ('author', 'event', 'group', 'selection', 'funding', 'media', 'issue', 'reprint', 'upcoming')


def _url(value):
    if not isinstance(value, str):
        return ''
    parts = urlsplit(value.strip())
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        return ''
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.startswith('utm_') and k not in ('fbclid', 'igshid')]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip('/'), urlencode(query), ''))


def _identity(signal):
    d = signal.detail or {}
    url = _url(signal.url or d.get('source_url'))
    keys = {('url', url)} if url else set()
    event = d.get('event') if isinstance(d.get('event'), dict) else {}
    title = event.get('name') or d.get('event_name') or signal.title
    if signal.happens_on and title:
        keys.add(('event', signal.happens_on.isoformat(), loose_key(title)))
    return keys or {('signal', signal.pk)}


def _posted_ids():
    ids = set()
    for d in Draft.objects.filter(Q(status=Draft.POSTED) | ~Q(placements=[])).select_related('proposal'):
        if d.status != Draft.POSTED and not d.placements:
            continue
        p = d.proposal
        if p.signal_id:
            ids.add(p.signal_id)
        for key in ('signals', 'more_signal_ids'):
            ids.update(i for i in (p.extra or {}).get(key, []) if type(i) is int)
    return ids


def _books(signal, quiet):
    """요약에 쉬는 책이 섞였다면 그 소식 전체를 제외한다."""
    d = signal.detail or {}
    ids = {i for i in d.get('book_ids', []) if type(i) is int}
    if signal.book_id:
        ids.add(signal.book_id)
    if not ids and d.get('book_hint'):
        found = find_book(d['book_hint'])
        if found:
            ids.add(found.pk)
    books = list(Book.objects.filter(pk__in=ids, is_published=True, visible=True).order_by('pk'))
    if ids & quiet or len(books) != len(ids):
        return None
    return books


def _blocked(signal):
    d = signal.detail or {}
    return signal.sensitive or not signal.relevant or d.get('status') == 'cancelled' or d.get('promoted') is True


def _groups(today, now, quiet):
    """최근 소식의 연결된 중복을 먼저 합친다. 취소·민감·게시 완료 사본이 있으면 그룹도 제외한다."""
    start = now - timedelta(days=7)
    signals = list(Signal.objects.filter(kind__in=SIGNAL_KINDS, found_at__gte=start, found_at__lte=now)
                   .select_related('book').order_by('found_at', 'pk'))
    posted = _posted_ids()
    blocked_keys = set()
    for s in Signal.objects.filter(pk__in=posted):
        blocked_keys |= _identity(s)
    groups = []
    for s in signals:
        identity = _identity(s)
        matches = [g for g in groups if g['keys'] & identity]
        if matches:
            group = matches[0]
            for other in matches[1:]:
                group['keys'] |= other['keys']
                group['signals'] += other['signals']
                groups.remove(other)
            group['keys'] |= identity
            group['signals'].append(s)
        else:
            groups.append({'keys': identity, 'signals': [s]})
    out = []
    for group in groups:
        if group['keys'] & blocked_keys or any(_blocked(s) for s in group['signals']):
            continue
        usable, books = [], {}
        for s in group['signals']:
            d = s.detail or {}
            if s.happens_on and not today - timedelta(days=6) <= s.happens_on <= today:
                continue
            if s.kind == Signal.MOMENT and (d.get('status') not in ('confirmed', 'done')
                                            or d.get('type') not in MOMENT_KINDS or d.get('date_unverified')):
                continue
            linked = _books(s, quiet)
            if linked is None:
                usable = []
                break
            if not s.title or len(s.title) > 500 or len(str(d.get('summary') or '')) > 600:
                continue
            usable.append(s)
            books.update({b.pk: b for b in linked})
        if usable:
            primary = usable[0]
            group.update(primary=primary, books=list(books.values()), story={
                'title': primary.title, 'summary': str((primary.detail or {}).get('summary') or ''),
                'date': (primary.happens_on or kst_today(primary.found_at)).isoformat(),
                'source_url': _url(primary.url or (primary.detail or {}).get('source_url')),
                'books': [b.title for b in books.values()]})
            out.append(group)
    return out


def _sent(key, exclude_proposal_id=None):
    sent = Proposal.objects.filter(candidate_key=key).exclude(pk=exclude_proposal_id).filter(
        Q(kind=Proposal.NOW, sent_at__isnull=False, status__in=(Proposal.SHOWN, Proposal.ACTED, Proposal.SKIPPED))
        | Q(briefing__sent_at__isnull=False))
    return any(not (p.extra or {}).get('content_preview_at')
               or (p.extra or {}).get('content_room_sent_at') for p in sent)


def _weekly(groups, key):
    if not groups or _sent(key):
        return None
    stories = [g['story'] for g in groups]
    signals = list({s.pk: s for g in groups for s in g['signals']}.values())
    books = list({b.pk: b for g in groups for b in g['books']}.values())
    urls = list(dict.fromkeys(s['source_url'] for s in stories if s['source_url']))
    form = 'standalone' if len(stories) == 1 else 'roundup'
    summary = '\n'.join(s['title'] + (' ― ' + s['summary'] if s['summary'] else '') for s in stories)
    return Candidate(id=key, kind='series_week', books=books, summary=summary,
                     facts={'series_form': form, 'expected_channel': 'blog', 'stories': stories, 'source_urls': urls,
                            'headline_hint': stories[0]['title'] if form == 'standalone' else '이번 주 한티재'},
                     urgency=2, signal=signals[0], more_signals=signals[1:], link='\n'.join(urls))


def _recent_books(now, exclude_proposal_id=None):
    rows = (Proposal.objects.filter(created_at__gte=now - timedelta(days=30))
            .exclude(pk=exclude_proposal_id).select_related('signal'))
    ids = set()
    for p in rows:
        if p.book_id:
            ids.add(p.book_id)
        if p.signal:
            if p.signal.book_id:
                ids.add(p.signal.book_id)
            ids.update(i for i in (p.signal.detail or {}).get('book_ids', []) if type(i) is int)
    return ids


def _reread(today, now, groups, quiet, occupied, key, exclude_proposal_id=None):
    if ((week_start(today) - ANCHOR).days // 7) % 2 or _sent(key, exclude_proposal_id):
        return None, 'not_due' if ((week_start(today) - ANCHOR).days // 7) % 2 else 'already_sent'
    rest = _recent_books(now, exclude_proposal_id) | quiet | occupied
    eligible = {b.pk: b for b in Book.objects.filter(is_published=True, visible=True,
                                                     published_date__lt=today - timedelta(days=180)).exclude(pk__in=rest)}
    choices = []
    for hook, on in upcoming(today, 14):
        for book in hook.books.all():
            if book.pk in eligible:
                choices.append((on, book.pk, book, f'{on.month}월 {on.day}일 {hook.name}',
                                {'hook': hook.name, 'date': on.isoformat()}, [_url(hook.source_url)] if _url(hook.source_url) else [],
                                hook.memorial, None))
    for group in groups:
        s = group['primary']
        if s.kind != Signal.NEWS:
            continue
        for book in group['books']:
            if book.pk in eligible:
                story = group['story']
                choices.append((s.happens_on or today, book.pk, book, story['title'] + ' ― ' + story['summary'],
                                {'story': story}, [story['source_url']] if story['source_url'] else [], False, s))
    if not choices:
        return None, 'no_hook'
    _, _, book, reason, facts, urls, memorial, signal = sorted(choices, key=lambda row: (row[0], row[1]))[0]
    return Candidate(id=key, kind='series_reread', books=[book], summary=f'『{book.title}』 다시 읽기 ― {reason}',
                     facts={**facts, 'series_form': 'reread', 'expected_channel': 'blog', 'source_urls': urls,
                            'published': book.published_date.isoformat()}, urgency=1, memorial=memorial,
                     signal=signal, link='\n'.join(urls)), 'generated'


def can_send(proposal, today, now):
    """저장한 연재 전체의 근거를 발송 직전에 다시 본다. 생성·미리보기 행 자체는 휴지 기간에 세지 않는다."""
    week = week_start(today).isoformat()
    weekly_key, reread_key = f'series:week:{week}', f'series:reread:{week}'
    extra = proposal.extra or {}
    if (WorkerState.get('series_mode', 'off') != 'live' or today.weekday() != 4
            or proposal.candidate_key not in (weekly_key, reread_key)
            or proposal.status in (Proposal.SKIPPED, Proposal.ACTED)
            or extra.get('content_room_sent_at')
            or (proposal.sent_at and not extra.get('content_preview_at'))
            or _sent(proposal.candidate_key, proposal.pk)):
        return False
    if any(d.status == Draft.POSTED or d.placements for d in proposal.drafts.all()):
        return False
    quiet = set(BookProfile.objects.filter(quiet_until__gte=today).values_list('book_id', flat=True))
    book_ids = {i for i in extra.get('book_ids', []) if type(i) is int}
    if proposal.book_id:
        book_ids.add(proposal.book_id)
    if (book_ids & quiet or Book.objects.filter(pk__in=book_ids, is_published=True, visible=True).count()
            != len(book_ids)):
        return False
    groups = _groups(today, now, quiet)
    live_ids = {s.pk for group in groups for s in group['signals']}
    source_ids = {i for i in extra.get('more_signal_ids', []) if type(i) is int}
    if proposal.signal_id:
        source_ids.add(proposal.signal_id)
    # 모음 중 한 소식만 게시·취소되어도 옛 본문 그대로 보낼 수 없다. 새 중복 원문도 _groups가 함께 검사한다.
    if source_ids - live_ids:
        return False
    if proposal.candidate_key == weekly_key:
        return bool(source_ids)
    candidate, _ = _reread(today, now, groups, quiet, set(), reread_key, proposal.pk)
    return bool(candidate and {b.pk for b in candidate.books} == book_ids
                and (candidate.signal.pk if candidate.signal else None) == proposal.signal_id)


def _source_errors(today):
    # 뉴스는 월요일, 나머지는 매일 확인한다. 해당 주기 실패를 무소식으로 바꾸지 않는다.
    failed = []
    for name in ('news', 'selection', 'moment'):
        value = WorkerState.get(f'marketing_error_{name}')
        try:
            day = date.fromisoformat(value)
        except (ValueError, TypeError):
            continue
        relevant = week_start(today) <= day <= today if name == 'news' else day == today
        if name == 'selection':
            # 연재는 05:30, 선정 수집은 06:10이다. 전날 마지막 시도가 실패했으면 아직 복구된 것이 아니다.
            relevant = relevant or (day <= today and value == WorkerState.get('marketing_last_selection_scan'))
        if relevant:
            failed.append(name)
    partial = WorkerState.objects.filter(key__startswith='selection_fail_').values_list('value', flat=True)
    if 'selection' not in failed and any(type(n) in (int, float) and n > 0 for n in partial):
        failed.append('selection')
    return failed


def items(today, now):
    """Friday 후보만 반환한다. 상태의 generated는 제안 재료 확인이며 실제 발송 완료가 아니다."""
    if WorkerState.get('series_mode', 'off') != 'live' or today.weekday() != 4:
        return []
    quiet = set(BookProfile.objects.filter(quiet_until__gte=today).values_list('book_id', flat=True))
    week = week_start(today).isoformat()
    groups = _groups(today, now, quiet)
    weekly = _weekly(groups, f'series:week:{week}')
    reread, reread_status = _reread(today, now, groups, quiet, {b.pk for b in weekly.books} if weekly else set(),
                                     f'series:reread:{week}')
    out = [c for c in (weekly, reread) if c]
    errors = _source_errors(today)
    status = ('generated' if out else 'source_failed' if errors else
              'already_sent' if _sent(f'series:week:{week}') else 'no_news')
    WorkerState.put('series_state', {'checked_at': now.isoformat(), 'week': week, 'status': status,
                                   'candidate_keys': [c.id for c in out], 'weekly_count': len(groups),
                                   'reread_status': reread_status, 'source_errors': errors})
    return out
