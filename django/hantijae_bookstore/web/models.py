from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import BaseModel


class NoticeQuerySet(models.QuerySet):
    def active(self, now=None):
        now = now or timezone.now()
        return (self.filter(state=Notice.POSTED, starts_at__lte=now)
                .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
                .order_by('-starts_at', '-id'))


class Notice(BaseModel):
    """첫 화면 맨 위 알림 띠. 관리자 화면·텔레그램 봇(/notice)·북펀드 자동 감지로 만든다."""
    ASKING, DRAFT, POSTED, REMOVED = 'asking', 'draft', 'posted', 'removed'
    STATE_CHOICES = ((ASKING, '내용 기다리는 중'), (DRAFT, '미리보기'), (POSTED, '게시 중'), (REMOVED, '내림'))

    message = models.CharField(max_length=200, blank=True, help_text='첫 화면 맨 위 한 줄 (60자 안쪽 권장)')
    link_url = models.URLField(max_length=500, blank=True)
    link_label = models.CharField(max_length=30, default='자세히 보기')
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(null=True, blank=True, help_text='비우면 내릴 때까지')
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default=POSTED)
    chat_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True, help_text='봇 대화에서 답장받을 메시지')
    created_by = models.CharField(max_length=100, blank=True)

    objects = NoticeQuerySet.as_manager()

    class Meta:
        ordering = ('-id',)
        verbose_name = verbose_name_plural = '알림 띠'

    def __str__(self):
        return self.message or f'알림 {self.pk}'


def current_notice(now=None):
    return Notice.objects.active(now).first()
