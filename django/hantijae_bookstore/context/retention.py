"""보관 기한이 지난 기록을 지운다. 워커가 하루 한 번 부른다."""
from datetime import timedelta

from django.conf import settings

from context.models import ContextEntry


def purge(now, days=None):
    days = days or settings.CONTEXT['RETENTION_DAYS']
    from context.notion_work import PREFIX
    # 업무는 완료·재개될 수 있다. 내용 없는 '잊기' 표식은 보존해 재수집을 막는다.
    deleted, _ = (ContextEntry.objects.filter(at__lt=now - timedelta(days=days))
                  .exclude(source=ContextEntry.NOTION, key__startswith=PREFIX, forgotten=True).delete())
    return deleted
