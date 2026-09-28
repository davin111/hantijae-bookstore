"""보관 기한이 지난 기록을 지운다. 워커가 하루 한 번 부른다."""
from datetime import timedelta

from django.conf import settings

from context.models import ContextEntry


def purge(now, days=None):
    days = days or settings.CONTEXT['RETENTION_DAYS']
    deleted, _ = ContextEntry.objects.filter(at__lt=now - timedelta(days=days)).delete()
    return deleted
