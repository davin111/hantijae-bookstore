"""공공 선정 감지(스펙 §5·§9-2). 매일 06:10(KST) 한 번: 처음 보는 발표만 읽어 한티재 책을 찾는다.
ISBN으로 맞으면 첫 화면 알림 띠에 바로 올리고(live 모드), 제목으로만 맞으면 [게시] 제안 카드를 보낸다."""
import logging
import time
from dataclasses import dataclass

from marketing.http import http_get, http_get_bytes
from marketing.models import SelectionAnnouncement, Signal
from marketing.selection_match import match_books, our_books
from marketing.selection_sources import SCANNERS, Announcement

log = logging.getLogger('intake')


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
