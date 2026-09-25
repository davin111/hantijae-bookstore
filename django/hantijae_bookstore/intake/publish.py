from django.db import transaction

from intake.drafts import invalidate_book_caches, lock_current
from intake.mapping import check_book
from intake.models import BookDraft


class PublishBlocked(Exception):
    def __init__(self, warnings):
        super().__init__('공개를 막는 항목이 있어요')
        self.warnings = warnings


def publish(draft_id, base_version):
    with transaction.atomic():
        draft = lock_current(draft_id, base_version)
        if draft.state != BookDraft.REVIEW:
            raise PublishBlocked([])
        ex = draft.extracted
        warnings = list(ex.get('_notes', [])) + check_book(
            draft.book, ex.get('_unresolved', []), ex.get('_edited', []), draft.source_text,
            ex.get('_source_quality', 0.0))
        blocking = [w for w in warnings if w['blocking']]
        if blocking:
            raise PublishBlocked(blocking)
        draft.book.is_published = True
        draft.book.save(update_fields=['is_published', 'updated_at'])
        draft.state = BookDraft.PUBLISHED
        draft.warnings = warnings
        draft.version += 1
        draft.save()
    invalidate_book_caches(draft.book)
    return draft
