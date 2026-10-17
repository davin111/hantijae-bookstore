from django.db import models

from core.models import BaseModel


class ApprovedImage(BaseModel):
    """검수된 한티재 원본만 등록. 파일은 VISUALS_ROOT/sources 아래에 보관한다."""
    book = models.ForeignKey('books.Book', on_delete=models.CASCADE)
    kind = models.CharField(max_length=12, choices=[('toc', '목차'), ('inside', '본문'), ('photo', '사진')])
    path = models.CharField(max_length=300, help_text='VISUALS_ROOT 기준 상대 경로')
    label = models.CharField(max_length=200, help_text='예: 목차 일부(1부)')
    source = models.CharField(max_length=500, help_text='원본 위치와 사용 승인 근거')
    active = models.BooleanField(default=True)


class CardJob(BaseModel):
    draft = models.ForeignKey('marketing.Draft', related_name='visual_jobs', on_delete=models.CASCADE)
    chat_id = models.BigIntegerField()
    reply_to = models.BigIntegerField()
    fingerprint = models.CharField(max_length=64)
    state = models.CharField(max_length=20, default='queued', db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    illustration_at = models.DateTimeField(null=True, blank=True)
    plan = models.JSONField(default=dict, blank=True)
    files = models.JSONField(default=list, blank=True)
    receipt = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        unique_together = ('draft', 'chat_id', 'fingerprint')
        ordering = ['id']
