"""운영자가 지정한 자료만 재개한다. 처리 중이거나 초안이 생긴 자료는 보존한다."""
from django.db import transaction

from intake.models import IntakeSource


class SourceQueueError(ValueError):
    pass


def _queue_locked(source, allowed):
    draft_id = source.drafts.order_by('id').values_list('id', flat=True).first()
    if draft_id:
        raise SourceQueueError(f'이미 연결된 초안 #{draft_id}이 있어요. 그 초안 카드에서 확인해 주세요. 새 초안은 만들지 않았어요.')
    if source.status not in allowed:
        raise SourceQueueError(f'자료 #{source.pk}는 {source.get_status_display()} 상태예요. 현재 상태를 유지했어요.')
    source.status, source.error, source.attempts = IntakeSource.QUEUED, '', 0
    source.save(update_fields=['status', 'error', 'attempts', 'updated_at'])
    return source


def retry_source(source_id):
    with transaction.atomic():
        source = IntakeSource.objects.select_for_update().filter(pk=source_id).first()
        if source is None:
            raise SourceQueueError('그런 자료가 없어요')
        return _queue_locked(source, (IntakeSource.FAILED,))


def ingest_source(folder_id, title):
    with transaction.atomic():
        source, _ = IntakeSource.objects.select_for_update().get_or_create(
            drive_folder_id=folder_id, defaults={'kind': IntakeSource.DRIVE, 'title': title})
        return _queue_locked(source, (IntakeSource.SEEN, IntakeSource.BASELINE,
                                     IntakeSource.IGNORED, IntakeSource.FAILED))
