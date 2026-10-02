import copy
from datetime import datetime

from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

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
    # 게시 중인 알림을 봇에서 고치면 여기에 먼저 담고, [반영]을 눌러야 위 칸으로 옮긴다
    pending = models.JSONField(null=True, blank=True, help_text='봇: 반영을 기다리는 수정안 (snapshot 형식)')
    previous = models.JSONField(null=True, blank=True, help_text='봇: 마지막 반영 전 값 {values, at} — 되돌리기용')

    objects = NoticeQuerySet.as_manager()

    VALUE_FIELDS = ('message', 'link_url', 'link_label', 'starts_at', 'ends_at')

    class Meta:
        ordering = ('-id',)
        verbose_name = verbose_name_plural = '알림 띠'

    def __str__(self):
        return self.message or f'알림 {self.pk}'

    def snapshot(self):
        """첫 화면에 보이는 값만 JSON으로 (수정안·되돌리기 저장용)."""
        snap = {f: getattr(self, f) for f in self.VALUE_FIELDS}
        return {f: (v.isoformat() if isinstance(v, datetime) else v) for f, v in snap.items()}

    def set_values(self, snap):
        for f in self.VALUE_FIELDS:
            v = snap.get(f)
            setattr(self, f, parse_datetime(v) if f.endswith('_at') and v else v)

    def proposal(self):
        """수정안을 입힌 사본 — 저장하지 않고 미리보기 카드에만 쓴다."""
        view = copy.copy(self)
        view.set_values(self.pending)
        return view


def current_notice(now=None):
    return Notice.objects.active(now).first()


class StoreClick(models.Model):
    """서점 버튼 클릭 기록 — 어떤 책을 어느 서점으로 보냈는지. IP·쿠키·세션은 저장하지 않는다."""
    STORE_CHOICES = (('aladin', '알라딘'), ('yes24', 'YES24'), ('kyobo', '교보문고'),
                     ('e_aladin', '알라딘 전자책'), ('e_yes24', 'YES24 전자책'), ('e_kyobo', '교보문고 전자책'), ('ridi', '리디'))

    book = models.ForeignKey('books.Book', related_name='store_clicks', on_delete=models.CASCADE)
    store = models.CharField(max_length=10, choices=STORE_CHOICES)
    referrer_host = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ('-id',)
        verbose_name = verbose_name_plural = '서점 클릭'
