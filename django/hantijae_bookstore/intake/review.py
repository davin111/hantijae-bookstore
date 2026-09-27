"""검수 방 '확인 부탁' — 노션·사이트 값이 다를 때 검수자가 고른 값으로 양쪽을 맞춘다.

항목 하나 = 텔레그램 메시지 하나. 선택지마다 {항목: 값}을 들고 있고, 고르면 그 값과 다른 쪽(노션/사이트)만 고친다.
게시 시점 값(before)과 지금 값이 다르면 누가 그사이 직접 고친 것이므로 덮어쓰지 않는다.
"""
import copy
from datetime import date

from django.db import transaction

from books.models import Book
from intake.drafts import invalidate_book_caches
from intake.models import ReviewItem

# 항목 → (사이트 Book 필드 또는 None=노션 전용, 노션 속성 타입). 노션 속성 이름은 항목 이름과 같다.
FIELDS = {
    '쪽수': ('page_count', 'number'),
    '가격': ('full_price', 'number'),
    '발행일': ('published_date', 'date'),
    '판형': ('size', 'select'),
    '부제': ('subtitle', 'rich_text'),
    'ISBN': (None, 'rich_text'),
}
NOTION, SITE = '노션', '사이트'


class ReviewError(Exception):
    def __init__(self, message, stale=False):
        super().__init__(message)
        self.stale = stale


def _norm(v):
    if v in ('', None, []):
        return None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _notion_read(prop):
    if not prop:
        return None
    t = prop.get('type')
    v = prop.get(t)
    if t in ('rich_text', 'title'):
        return _norm(''.join(x.get('plain_text', '') for x in v or []))
    if t == 'select':
        return v['name'] if v else None
    if t == 'date':
        return v['start'][:10] if v else None
    return _norm(v)


def _notion_write(field, value):
    kind = FIELDS[field][1]
    if kind == 'number':
        return {'number': value}
    if kind == 'rich_text':
        return {'rich_text': [{'type': 'text', 'text': {'content': value}}] if value else []}
    if kind == 'select':
        return {'select': {'name': value} if value else None}
    return {'date': {'start': value} if value else None}


def _site_read(book, field):
    v = getattr(book, FIELDS[field][0])
    return _norm(v.isoformat() if isinstance(v, date) else v)


def _site_value(field, value):
    if FIELDS[field][1] == 'date':
        return date.fromisoformat(value)
    return '' if value is None and field == '부제' else value


def fields_of(spec):
    fields = sorted({f for o in spec['options'] for f in o['set']})
    unknown = [f for f in fields if f not in FIELDS]
    if unknown:
        raise ValueError(f'모르는 항목: {unknown}')
    return fields


def snapshot(book_id, page_id, fields, notion):
    page = notion.get_page(page_id) if page_id else None
    book = Book.objects.get(pk=book_id) if book_id else None
    return {f: {'notion': _notion_read(page['properties'].get(f)) if page else None,
                'site': _site_read(book, f) if book and FIELDS[f][0] else None} for f in fields}


def normalize_snapshot(snap):
    return {f: {side: _norm(v) for side, v in sides.items()} for f, sides in snap.items()}


def create_item(batch, seq, spec, notion, before=None):
    fields = fields_of(spec)
    return ReviewItem.objects.create(
        batch=batch, seq=seq, title=spec['title'], body=spec.get('body', ''), book_id=spec.get('book_id'),
        notion_page_id=spec.get('notion_page_id', ''), options=spec['options'],
        before=before if before is not None else snapshot(spec.get('book_id'), spec.get('notion_page_id', ''), fields, notion))


def _current(item, notion):
    return snapshot(item.book_id, item.notion_page_id, list(item.before), notion)


def _commit(item, writes, notion):
    """writes = [(곳, 항목, 새 값)]. 외부(노션)를 먼저 쓰고, 실패하면 예외가 트랜잭션을 되돌려 사이트는 그대로 남는다."""
    props = {f: _notion_write(f, v) for side, f, v in writes if side == NOTION}
    site = {FIELDS[f][0]: _site_value(f, v) for side, f, v in writes if side == SITE}
    if props:
        notion.update_page(item.notion_page_id, props)
    if site:
        book = Book.objects.select_for_update().get(pk=item.book_id)
        for col, v in site.items():
            setattr(book, col, v)
        book.save(update_fields=list(site) + ['updated_at'])
        invalidate_book_caches(book)


def choose(item_id, index, actor, notion):
    """고른 선택지를 반영한다. 반환: (항목, [(곳, 항목, 전, 후)])."""
    stale = False
    with transaction.atomic():
        item = ReviewItem.objects.select_for_update().get(pk=item_id)
        if item.status != ReviewItem.PENDING:
            raise ReviewError('이미 처리된 항목이에요')
        if not 0 <= index < len(item.options):
            raise ReviewError('없는 선택지예요')
        cur = _current(item, notion)
        if cur != item.before:
            item.status = ReviewItem.STALE
            item.save(update_fields=['status', 'updated_at'])
            stale = True
        else:
            changed = []
            for f, v in item.options[index]['set'].items():
                v = _norm(v)
                if item.notion_page_id and cur[f]['notion'] != v:
                    changed.append([NOTION, f, cur[f]['notion'], v])
                if item.book_id and FIELDS[f][0] and cur[f]['site'] != v:
                    changed.append([SITE, f, cur[f]['site'], v])
            _commit(item, [(side, f, new) for side, f, _, new in changed], notion)
            item.status = ReviewItem.APPLIED if item.options[index]['set'] else ReviewItem.KEPT
            item.chosen, item.decided_by, item.changed = index, actor, changed
            item.save()
    if stale:
        raise ReviewError('그사이 값이 바뀌어서 반영하지 않았어요', stale=True)
    return item, [tuple(c) for c in item.changed]


def undo(item_id, actor, notion):
    """반영을 되돌리고 다시 고를 수 있게 연다. 반영 뒤 누가 값을 또 고쳤으면 되돌리지 않는다."""
    with transaction.atomic():
        item = ReviewItem.objects.select_for_update().get(pk=item_id)
        if item.status not in (ReviewItem.APPLIED, ReviewItem.KEPT):
            raise ReviewError('되돌릴 수 없는 항목이에요')
        if item.status == ReviewItem.APPLIED:
            expected = copy.deepcopy(item.before)
            for side, f, _, new in item.changed:
                expected[f]['notion' if side == NOTION else 'site'] = new
            if _current(item, notion) != expected:
                raise ReviewError('반영한 뒤에 값이 또 바뀌어서 되돌리지 않았어요')
            _commit(item, [(side, f, old) for side, f, old, _ in item.changed], notion)
        item.status, item.chosen, item.decided_by, item.changed = ReviewItem.PENDING, None, '', []
        item.save()
    return item
