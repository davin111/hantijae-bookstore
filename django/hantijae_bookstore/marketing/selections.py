"""공공 선정 감지(스펙 §5·§9-2). 매일 06:10(KST) 한 번: 처음 보는 발표만 읽어 한티재 책을 찾는다.
ISBN으로 맞으면 첫 화면 알림 띠에 바로 올리고(live 모드), 제목으로만 맞으면 [게시] 제안 카드를 보낸다."""
import logging
import time
from dataclasses import dataclass
from datetime import timedelta

from intake import messages, notices
from intake.models import WorkerState
from marketing.http import http_get, http_get_bytes
from marketing.models import SelectionAnnouncement, Signal
from marketing.selection_match import match_books, our_books
from marketing.selection_sources import SCANNERS, Announcement
from web.models import Notice
from web.pages import absolute_url

log = logging.getLogger('intake')

NOTICE_DAYS = 30
FAIL_ALERT_DAYS = 3


@dataclass
class Found:
    signal: Signal
    how: str
    announcement: Announcement


def _record(ann, books):
    hits = match_books(ann.texts, books)
    SelectionAnnouncement.objects.create(key=ann.key[:200], source=ann.source, label=ann.label[:200],
                                         url=ann.url[:1000], posted_on=ann.posted_on, withdrawal=ann.withdrawal,
                                         matched=len(hits))
    out = []
    for hit in hits:
        sig, created = Signal.objects.get_or_create(
            key=f'selection:{ann.key}:{hit.book.id}'[:200],
            defaults={'kind': Signal.SELECTION, 'book': hit.book, 'title': ann.label[:500], 'url': ann.url[:1000],
                      'happens_on': ann.posted_on,
                      'detail': {'source': ann.source, 'match': hit.how, 'withdrawal': ann.withdrawal,
                                 'fresh': ann.fresh},
                      'relevant': ann.fresh and not ann.withdrawal})
        if created:
            out.append(Found(sig, hit.how, ann))
    return out


def collect(today, get_text=http_get, get_bytes=http_get_bytes, sleep=time.sleep):
    """(새로 찾은 것, 실패한 출처 아이디). 한 출처가 실패해도 나머지는 읽는다.
    모두 실패하면 예외 — tasks._guard가 관리자에게 하루 한 번 알린다."""
    seen = set(SelectionAnnouncement.objects.values_list('key', flat=True))
    books = our_books()
    found, failed = [], []
    for sid, _name, scan in SCANNERS:
        try:
            anns = scan(today, seen, get_text, get_bytes, sleep)
        except Exception:
            log.warning('selection scan %s failed', sid, exc_info=True)
            failed.append(sid)
            continue
        for ann in anns:
            if ann.key in seen:
                continue
            seen.add(ann.key)
            found += _record(ann, books)
    if failed and len(failed) == len(SCANNERS):
        raise RuntimeError('공공 선정 발표를 한 곳도 읽지 못했어요: ' + ', '.join(failed))
    return found, failed


def notice_message(title, label):
    """『제목』 ○○ 선정 — 알림 띠 한 줄(60자) 안에 들게 제목을 줄인다."""
    tail = f' {label} 선정'
    room = notices.MAX_LEN - len(tail) - 2   # 낫표 두 글자
    name = title if len(title) <= room else title[:max(room - 1, 1)].rstrip() + '…'
    return f'『{name}』{tail}'


def announce(deps, found, now):
    """ISBN으로 맞고 live 모드면 바로 게시, 아니면 미리보기(DRAFT). 카드는 모드에 맞는 방(target_chat)으로."""
    m = deps.bot.marketing
    book, ann = found.signal.book, found.announcement
    post = found.how == 'isbn' and m.mode() == 'live'
    notice = Notice.objects.create(
        message=notice_message(book.title, ann.label), link_url=absolute_url(f'/book={book.id}'),
        link_label='책 보기', starts_at=now, ends_at=now + timedelta(days=NOTICE_DAYS),
        state=Notice.POSTED if post else Notice.DRAFT, created_by='공공 선정 자동 감지')
    Signal.objects.filter(pk=found.signal.pk).update(
        detail={**found.signal.detail, 'notice_id': notice.id, 'posted': post})
    chat = m.target_chat()
    if not chat:
        return notice
    if post:
        head = f'🏅 {ann.label} 선정 — 『{book.title}』\n사이트 첫 화면에 알림을 올렸어요. 발표: {ann.url}'
    else:
        how = ' (ISBN이 아니라 제목으로 찾았어요)' if found.how == 'title' else ''
        head = (f'🏅 {ann.label} 선정 도서로 보여요 — 『{book.title}』{how}\n'
                f'발표를 확인하고 첫 화면에 올릴까요? 발표: {ann.url}')
    sent = deps.bot.tg.send_message(chat, messages.notice_card(notice, head=head),
                                    buttons=messages.notice_buttons(notice))
    notices.attach_message(notice, chat, sent['message_id'])
    return notice


def _track_failures(deps, failed):
    """같은 출처가 사흘 연속 실패하면(페이지 형식이 바뀌었을 수 있다) 관리자에게 한 번 알린다."""
    for sid, name, _scan in SCANNERS:
        key = f'selection_fail_{sid}'
        if sid not in failed:
            WorkerState.put(key, 0)
            continue
        streak = (WorkerState.get(key) or 0) + 1
        WorkerState.put(key, streak)
        if streak == FAIL_ALERT_DAYS:
            deps.bot.notify_admin(f'⚠️ 공공 선정: {name} 발표를 {streak}일째 읽지 못했어요. '
                                  f'페이지 형식이 바뀌었는지 확인해 주세요')


def run_scan(deps, today, now, **collect_kwargs):
    found, failed = collect(today, **collect_kwargs)
    for f in found:
        try:
            if f.announcement.withdrawal:
                deps.bot.notify_admin(f'⚠️ {f.announcement.label} 철회·취소 공고 목록에 『{f.signal.book.title}』 포함 — '
                                      f'확인해 주세요: {f.announcement.url}')
            elif f.announcement.fresh:
                announce(deps, f, now)
        except Exception:
            log.warning('selection announce failed: %s', f.signal.key, exc_info=True)
            try:
                deps.bot.notify_admin(f'⚠️ 공공 선정: 『{f.signal.book.title}』 알림을 보내지 못했어요 — '
                                      f'확인해 주세요: {f.announcement.url}')
            except Exception:
                log.warning('selection admin notify failed: %s', f.signal.key, exc_info=True)
    _track_failures(deps, failed)
    return found
