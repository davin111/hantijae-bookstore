"""초안 = is_published=False 인 Book. 모든 변경은 버전·잠금·이력과 함께."""
import json
import os

from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from books.models import Author, Book, BookAuthor, BookSeries, Category, Series
from intake.images import to_jpeg
from intake.extract import is_verbatim
from intake.llm import complete_json
from intake.mapping import (MAX_PRICE, ROLE_TO_TYPE, TYPE_TO_ROLE, aladin_search_url, book_label, check_book,
                            find_isbn_duplicate, format_isbn, match_name, normalize_extraction, normalize_size,
                            parse_date, to_int, warning)
from intake.models import BookDraft, DraftRevision, PendingPatch
from intake.prompts import PATCH_SYSTEM, build_patch_user

PATCHABLE = ('title', 'subtitle', 'authors', 'series', 'series_number', 'category', 'size', 'page_count',
             'full_price', 'isbn', 'published_date', 'short_description', 'description')


class PatchError(Exception):
    pass


class StaleError(Exception):
    pass


def invalidate_book_caches(book):
    keys = ['book_count', 'series'] + [f'series_{bs.series_id}' for bs in book.series.all()]
    cache.delete_many(keys)


def _default_series():
    return Series.objects.get_or_create(name='단행본', defaults={'series_type': Series.NORMAL})[0]


def resolve_author(name):
    """초기 이관 때 같은 이름의 Author가 여러 행 생겼다. 가장 최근 행을 재사용한다."""
    matches = Author.objects.filter(name=name).order_by('-id')
    author = matches.first() or Author.objects.create(name=name)
    note = None
    if matches.count() > 1:
        note = warning('author_multiple', f"동명 저자 '{name}' {matches.count()}명 중 #{author.id}를 연결했어요", audience='admin')
    return author, note


def book_snapshot(book):
    bs = book.series.select_related('series').first()
    return {
        'title': book.title, 'subtitle': book.subtitle,
        'authors': [{'name': ba.author.name, 'role': TYPE_TO_ROLE.get(ba.author_type, '지은이')}
                    for ba in book.authors.select_related('author').order_by('id')],
        'series': bs.series.name if bs else None, 'series_number': bs.index if bs else None,
        'category': book.category.name, 'size': book.size, 'page_count': book.page_count,
        'full_price': book.full_price, 'isbn': book.isbn,
        'published_date': book.published_date.isoformat() if book.published_date else None,
        'short_description': book.short_description, 'description': book.description,
    }


def _draft_dir(draft):
    path = os.path.join(settings.INTAKE['WORK_DIR'], 'drafts', str(draft.id))
    os.makedirs(path, exist_ok=True)
    return path


def refresh_warnings(draft):
    ex = draft.extracted
    draft.warnings = list(ex.get('_notes', [])) + check_book(
        draft.book, ex.get('_unresolved', []), ex.get('_edited', []), draft.source_text, ex.get('_source_quality', 0.0))
    draft.save(update_fields=['warnings', 'updated_at'])


def create_draft(source, result):
    categories = {c.name: c.id for c in Category.objects.all()}
    series = {s.name: s.id for s in Series.objects.all()}
    n = normalize_extraction(result.data, categories, series)
    f = n.fields
    notes = list(n.notes)
    dup = find_isbn_duplicate(f['isbn'])
    if dup:
        # Book.isbn 은 unique 라 그대로 넣으면 IntegrityError. 비워 두고 차단 경고로 알린다.
        notes.append(warning('isbn_duplicate', f"이미 사이트에 있는 {book_label(dup)}과 ISBN이 같아요 — 같은 책이면 폐기해 주세요", True))
        f = dict(f, isbn=None, aladin_url='')
    with transaction.atomic():
        book = Book.objects.create(
            title=f['title'] or source.title, subtitle=f['subtitle'],
            short_description=f['short_description'], description=f['description'],
            full_price=f['full_price'] or 0, page_count=f['page_count'] or 0, size=f['size'], isbn=f['isbn'],
            published_date=f['published_date'] or timezone.localdate(),
            category_id=f['category_id'] or Category.objects.order_by('id').values_list('id', flat=True).first(),
            aladin_url=f['aladin_url'], visible=True, is_published=False)
        for name, type_ in n.authors:
            author, note = resolve_author(name)
            notes += [note] if note else []
            BookAuthor.objects.create(book=book, author=author, author_type=type_)
        BookSeries.objects.create(book=book, series_id=n.series_id or _default_series().id, index=n.series_index)
        draft = BookDraft.objects.create(
            source=source, book=book, state=BookDraft.REVIEW, source_text=result.source_text,
            extracted={**result.data, '_unresolved': n.unresolved, '_edited': [], '_notes': notes,
                       '_isbn_addon': n.isbn_addon, '_source_quality': result.source_quality})
        if result.front_cover:
            book.cover_image.save('cover.jpg', ContentFile(to_jpeg(result.front_cover, 1600)), save=False)
        options = []
        for i, path in enumerate(result.cover_3d_alternatives):
            out = os.path.join(_draft_dir(draft), f'3d-{i}.jpg')
            with open(out, 'wb') as fh:
                fh.write(to_jpeg(path, 1600))
            options.append(out)
        index = result.cover_3d_alternatives.index(result.cover_3d) if result.cover_3d in result.cover_3d_alternatives else 0
        if options:
            with open(options[index], 'rb') as fh:
                book.cover_image_3d.save('cover3d.jpg', ContentFile(fh.read()), save=False)
        book.save()
        draft.files = {'press_release': os.path.basename(result.press_release),
                       'cover_3d_options': options, 'cover_3d_index': index}
        draft.save()
        refresh_warnings(draft)
    return draft


def _set_field(book, field, value):
    validate_change(book, field, value)
    if field in ('title', 'subtitle', 'short_description', 'description'):
        v = str(value or '').strip()
        if field == 'title' and not v:
            raise PatchError('제목은 비울 수 없어요')
        setattr(book, field, v)
    elif field in ('full_price', 'page_count'):
        v = to_int(value)
        if not v or (field == 'full_price' and v > MAX_PRICE):
            raise PatchError(f'{value}은(는) 올바른 숫자가 아니에요')
        setattr(book, field, v)
    elif field == 'size':
        v = normalize_size(value)
        if not v:
            raise PatchError(f"판형 '{value}'을(를) 이해하지 못했어요 (예: 130*200)")
        book.size = v
    elif field == 'isbn':
        v = format_isbn(value)
        if not v:
            raise PatchError(f"ISBN '{value}'이(가) 올바르지 않아요")
        book.isbn, book.aladin_url = v, aladin_search_url(v)
    elif field == 'published_date':
        v = parse_date(value)
        if not v:
            raise PatchError(f"발행일 '{value}'을(를) 이해하지 못했어요")
        book.published_date = v
    elif field == 'category':
        pk = match_name(value, {c.name: c.id for c in Category.objects.all()})
        if not pk:
            raise PatchError(f"'{value}' 분야를 찾지 못했어요")
        book.category_id = pk
    elif field == 'authors':
        if not isinstance(value, list) or not value:
            raise PatchError('저자 목록이 비어 있어요')
        book.authors.all().delete()
        for a in value:
            author, _ = resolve_author(str(a.get('name', '')).strip())
            BookAuthor.objects.create(book=book, author=author,
                                      author_type=ROLE_TO_TYPE.get(a.get('role', ''), BookAuthor.NORMAL))
    elif field in ('series', 'series_number'):
        bs = book.series.first() or BookSeries(book=book, series=_default_series())
        if field == 'series':
            pk = match_name(value, {s.name: s.id for s in Series.objects.all()})
            if not pk:
                raise PatchError(f"'{value}' 시리즈를 찾지 못했어요")
            bs.series_id = pk
        else:
            bs.index = (str(value).strip() or None) if value is not None else None
        bs.save()
    else:
        raise PatchError(f'바꿀 수 없는 항목이에요: {field}')


def _apply_changes(draft, changes, request_text, actor):
    book = draft.book
    before = book_snapshot(book)
    fields = []
    for ch in changes:
        _set_field(book, ch['field'], ch.get('new_value'))
        fields.append(ch['field'])
    book.save()
    after = book_snapshot(book)
    diff = [{'field': f, 'old': before[f], 'new': after[f]} for f in dict.fromkeys(fields) if before[f] != after[f]]
    ex = dict(draft.extracted)
    ex['_unresolved'] = [u for u in ex.get('_unresolved', []) if u not in fields]
    ex['_edited'] = sorted(set(ex.get('_edited', [])) | set(fields))
    if 'isbn' in fields:
        ex['_notes'] = [n for n in ex.get('_notes', []) if n.get('code') != 'isbn_duplicate']
    draft.extracted = ex
    draft.version += 1
    draft.save()
    refresh_warnings(draft)
    rev = DraftRevision.objects.create(draft=draft, version=draft.version, changes=diff,
                                       request_text=request_text, requested_by=actor)
    if book.is_published:
        invalidate_book_caches(book)
    return rev


HISTORY_LIMIT = 50
_STATUS_LABEL = {PendingPatch.APPLIED: '반영됨', PendingPatch.CANCELLED: '취소됨', PendingPatch.STALE: '만료'}


def _clip(v, n=80):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    s = (s or '').replace('\n', ' ')
    return s if len(s) <= n else s[:n - 1] + '…'


def conversation_history(draft, limit=HISTORY_LIMIT):
    """같은 초안에서 오간 요청·봇 응답·결과를 오래된 순으로 (최근 limit건)."""
    rows = list(PendingPatch.objects.filter(draft=draft).order_by('-id')[:limit])[::-1]
    out = []
    for p in rows:
        if p.changes:
            bot = '제안 ' + '; '.join(f"{c['field']}→{_clip(c.get('new_value'), 60)}" for c in p.changes)
        elif p.questions:
            bot = '질문 ' + ' / '.join(p.questions)
        else:
            bot = '변경 없음'
        status = _STATUS_LABEL.get(p.status) or ('답변 대기' if p.questions and not p.changes else '반영 대기')
        out.append(f'{p.created_at:%m-%d %H:%M} {p.requested_by}: "{_clip(p.request_text, 200)}" / 봇: {bot} / 결과: {status}')
    return out


def cancel_open_patches(draft):
    return PendingPatch.objects.filter(draft=draft, status=PendingPatch.PROPOSED).update(status=PendingPatch.CANCELLED)


def validate_change(book, field, value):
    """제안과 실행에서 같은 입력을 검증한다. 관계 모델이나 공개 내용은 변경하지 않는다."""
    if field in ('title', 'subtitle', 'short_description', 'description'):
        if not isinstance(value, str) or (field == 'title' and not value.strip()):
            raise PatchError('제목과 소개에는 글을 입력해 주세요')
        try:
            book._meta.get_field(field).run_validators(value)
        except ValidationError:
            raise PatchError('입력한 글이 해당 항목에 저장할 수 있는 길이를 넘었어요')
    elif field in ('full_price', 'page_count'):
        v = to_int(value)
        if not v or v < 0 or v > (MAX_PRICE if field == 'full_price' else 2147483647):
            raise PatchError('가격과 쪽수는 올바른 양수로 입력해 주세요')
    elif field == 'size' and not normalize_size(value):
        raise PatchError('판형을 이해하지 못했어요 (예: 130*200)')
    elif field == 'isbn':
        isbn = format_isbn(value)
        if not isbn:
            raise PatchError('ISBN이 올바르지 않아요')
        if Book.objects.filter(isbn=isbn).exclude(pk=book.pk).exists():
            raise PatchError('같은 ISBN의 책이 이미 있어요')
    elif field == 'published_date' and not parse_date(value):
        raise PatchError('발행일을 이해하지 못했어요')
    elif field in ('category', 'series'):
        model = Category if field == 'category' else Series
        if not match_name(value, {x.name: x.id for x in model.objects.all()}):
            label = '분류' if field == 'category' else '시리즈'
            raise PatchError(f"'{value}' {label}는 아직 등록되지 않았어요. 기존 목록을 확인하거나 관리자에게 새 항목 등록을 요청해 주세요. 수정안은 저장하지 않았어요.")
    elif field == 'authors':
        if not isinstance(value, list) or not value or any(
                not isinstance(a, dict) or not isinstance(a.get('name'), str) or not a['name'].strip()
                or len(a['name']) > Author._meta.get_field('name').max_length
                or a.get('role') not in ROLE_TO_TYPE for a in value):
            raise PatchError('저자 이름과 역할을 확인해 주세요. 그림 등 지원하지 않는 역할은 지은이로 바꾸지 않아요.')
    elif field == 'series_number':
        length = BookSeries._meta.get_field('index').max_length
        if value is not None and (not isinstance(value, (str, int)) or len(str(value)) > length):
            raise PatchError('시리즈 번호가 너무 길거나 올바르지 않아요')


def open_patches(draft):
    return list(PendingPatch.objects.filter(draft=draft, status=PendingPatch.PROPOSED,
                                           base_version=draft.version).order_by('id'))


def propose_patch(draft, request_text, actor, client, parent_patch=None):
    """반환하는 PendingPatch 에는 저장되지 않는 속성 reply_message·cancelled_previous 가 붙는다(봇 응답용)."""
    snap = book_snapshot(draft.book)
    history = conversation_history(draft)
    opened = [p for p in open_patches(draft) if p.changes or p.questions]
    if parent_patch and (parent_patch.status != PendingPatch.PROPOSED
                         or parent_patch.draft_id != draft.pk or parent_patch.base_version != draft.version
                         or parent_patch.pk not in [p.pk for p in opened]):
        raise StaleError('이미 처리됐거나 이전 버전의 수정안이에요. 최신 책 카드에 답장해 주세요')
    if len(opened) > 1:
        if not parent_patch or parent_patch.pk not in [p.pk for p in opened]:
            raise PatchError('대기 수정안이 여러 개예요. 이어서 고칠 수정안에 답장해 주세요')
        previous = parent_patch
    else:
        previous = opened[0] if opened else None
    pending = {'changes': previous.changes, 'questions': previous.questions} if previous else None
    try:
        prompt = build_patch_user(snap, draft.source_text, request_text, history, pending=pending,
                                  require_full_source=bool(draft.files.get('source_revision')))
    except ValueError as e:
        raise PatchError(str(e)) from e
    reply = complete_json(client, PATCH_SYSTEM, prompt)
    cancel = bool(reply.get('cancel_previous'))
    incoming = [] if cancel else [
        c for c in reply.get('changes') or []
        if isinstance(c, dict) and c.get('field') in PATCHABLE]
    addition = reply.get('append_description') if not cancel else None
    if addition:
        if not isinstance(addition, str) or not (is_verbatim(addition, request_text) or is_verbatim(addition, draft.source_text)):
            raise PatchError('추가할 문장이 원자료와 일치하지 않아 수정안을 저장하지 않았어요. 원문을 다시 확인해 주세요')
        if any(c['field'] == 'description' for c in incoming):
            raise PatchError('본문 교체와 추가 요청이 겹쳐 수정안을 저장하지 않았어요. 추가할 부분을 다시 알려 주세요')
        base = next((c['new_value'] for c in previous.changes if c['field'] == 'description'), snap['description']) if previous else snap['description']
        incoming.append({'field': 'description', 'new_value': (base.rstrip() + '\n\n' + addition.strip()).strip()})
    questions = [] if cancel else [str(q) for q in reply.get('questions') or []][:3]
    replace = bool(incoming or questions)
    merged = {c['field']: c for c in previous.changes} if previous and replace else {}
    for c in incoming:
        validate_change(draft.book, c['field'], c.get('new_value'))
        merged[c['field']] = c
    changes = [c for c in merged.values() if c.get('new_value') != snap.get(c['field'])]
    for c in changes:
        validate_change(draft.book, c['field'], c.get('new_value'))
    with transaction.atomic():
        current = lock_current(draft.pk, draft.version)
        current_ids = [p.pk for p in open_patches(current) if p.changes or p.questions]
        if current_ids != [p.pk for p in opened] or current.source_text != draft.source_text:
            raise StaleError('그사이 다른 수정이 있었어요. 최신 카드에서 다시 요청해 주세요')
        if cancel:
            if previous:
                PendingPatch.objects.filter(pk=previous.pk).update(status=PendingPatch.CANCELLED)
        elif previous and replace:
            PendingPatch.objects.filter(pk=previous.pk).update(status=PendingPatch.CANCELLED)
        patch = PendingPatch.objects.create(
            draft=draft, base_version=draft.version, changes=changes, questions=questions, request_text=request_text,
            requested_by=actor, status=PendingPatch.CANCELLED if cancel else PendingPatch.PROPOSED)
    patch.reply_message = str(reply.get('message') or '').strip()[:500]
    patch.cancelled_previous = cancel
    return patch


def lock_current(draft_id, base_version):
    draft = BookDraft.objects.select_for_update().select_related('book').get(pk=draft_id)
    if draft.version != base_version or draft.state not in (BookDraft.REVIEW, BookDraft.PUBLISHED):
        raise StaleError('그사이 다른 분이 처리했어요. 최신 메시지에서 다시 해 주세요')
    return draft


def apply_patch(patch_id, actor):
    stale = None
    with transaction.atomic():
        patch = PendingPatch.objects.select_for_update().get(pk=patch_id)
        draft = BookDraft.objects.select_for_update().select_related('book').get(pk=patch.draft_id)
        if patch.status != PendingPatch.PROPOSED:
            stale = '이미 처리된 제안이에요'
        elif patch.base_version != draft.version or draft.state not in (BookDraft.REVIEW, BookDraft.PUBLISHED):
            patch.status = PendingPatch.STALE
            patch.save()
            stale = '그사이 다른 수정이 있었어요. 다시 요청해 주세요'
        elif patch.questions or not patch.changes:
            raise PatchError('아직 확인할 내용이 있거나 반영할 변경이 없어요. 수정안에 답장해 주세요')
        else:
            rev = _apply_changes(draft, patch.changes, patch.request_text, actor)
            patch.status = PendingPatch.APPLIED
            patch.save()
    if stale:
        raise StaleError(stale)
    return draft, rev


def revert_revision(revision_id, actor):
    with transaction.atomic():
        rev = DraftRevision.objects.select_for_update().get(pk=revision_id)
        if rev.reverted:
            raise StaleError('이미 되돌린 수정이에요')
        draft = BookDraft.objects.select_for_update().select_related('book').get(pk=rev.draft_id)
        changes = [{'field': c['field'], 'new_value': c['old']} for c in rev.changes if c['field'] in PATCHABLE]
        new_rev = _apply_changes(draft, changes, f'되돌리기 #{rev.id}', actor)
        rev.reverted = True
        rev.save()
    return draft, new_rev


def replace_front_cover(draft_id, image_path, actor):
    with transaction.atomic():
        draft = BookDraft.objects.select_for_update().select_related('book').get(pk=draft_id)
        draft.book.cover_image.save('cover.jpg', ContentFile(to_jpeg(image_path, 1600)), save=True)
        draft.version += 1
        draft.save()
        DraftRevision.objects.create(draft=draft, version=draft.version, requested_by=actor, request_text='앞표지 사진',
                                     changes=[{'field': 'front_cover', 'old': '이전 이미지', 'new': '새 사진'}])
        refresh_warnings(draft)
        if draft.book.is_published:
            invalidate_book_caches(draft.book)
    return draft


def cycle_3d(draft_id, base_version, actor):
    with transaction.atomic():
        draft = lock_current(draft_id, base_version)
        options = draft.files.get('cover_3d_options', [])
        if len(options) < 2:
            raise PatchError('다른 입체 이미지가 없어요')
        index = (draft.files.get('cover_3d_index', 0) + 1) % len(options)
        with open(options[index], 'rb') as fh:
            draft.book.cover_image_3d.save('cover3d.jpg', ContentFile(fh.read()), save=True)
        draft.files = dict(draft.files, cover_3d_index=index)
        draft.version += 1
        draft.save()
        DraftRevision.objects.create(draft=draft, version=draft.version, requested_by=actor, request_text='입체 이미지 변경',
                                     changes=[{'field': 'cover_3d', 'old': options[index - 1], 'new': options[index]}])
        if draft.book.is_published:
            invalidate_book_caches(draft.book)
    return draft


def discard(draft_id, base_version):
    with transaction.atomic():
        draft = lock_current(draft_id, base_version)
        if draft.state == BookDraft.PUBLISHED:
            raise PatchError('이미 공개된 책은 여기서 지울 수 없어요 (관리자 페이지 사용)')
        draft.book.delete()
        draft.book = None          # SET_NULL은 DB에만 반영되므로 메모리 객체도 비워야 save 시 FK 오류가 없다
        draft.state = BookDraft.DISCARDED
        draft.version += 1
        draft.save()
    return draft
