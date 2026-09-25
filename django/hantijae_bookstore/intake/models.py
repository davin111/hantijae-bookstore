from django.db import models

from core.models import BaseModel


class IntakeSource(BaseModel):
    DRIVE, TELEGRAM = 'drive', 'telegram'
    KIND_CHOICES = ((DRIVE, '드라이브'), (TELEGRAM, '텔레그램'))
    SEEN, BASELINE, QUEUED, PROCESSING, PROCESSED, IGNORED, FAILED = (
        'seen', 'baseline', 'queued', 'processing', 'processed', 'ignored', 'failed')
    STATUS_CHOICES = ((SEEN, '감지됨'), (BASELINE, '기준선(무시)'), (QUEUED, '처리 대기'),
                      (PROCESSING, '처리 중'), (PROCESSED, '처리 완료'), (IGNORED, '건너뜀'), (FAILED, '실패'))

    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    drive_folder_id = models.CharField(max_length=200, unique=True, null=True, blank=True)
    title = models.CharField(max_length=500, help_text="폴더명 또는 텔레그램 요청 설명")
    path = models.CharField(max_length=1000, blank=True, help_text="드라이브 경로 또는 tg:<chat>:<message>")
    fingerprint = models.CharField(max_length=64, blank=True)
    stable_since = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=SEEN)
    local_dir = models.CharField(max_length=1000, blank=True, help_text="텔레그램으로 받은 파일 저장 위치")
    requested_chat_id = models.BigIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)

    def __str__(self):
        return f'{self.get_kind_display()} {self.title} ({self.get_status_display()})'


class BookDraft(BaseModel):
    EXTRACTING, REVIEW, PUBLISHED, DISCARDED, FAILED = 'extracting', 'review', 'published', 'discarded', 'failed'
    STATE_CHOICES = ((EXTRACTING, '추출 중'), (REVIEW, '검수 중'), (PUBLISHED, '공개됨'),
                     (DISCARDED, '폐기'), (FAILED, '실패'))

    source = models.ForeignKey(IntakeSource, related_name='drafts', on_delete=models.PROTECT)
    book = models.OneToOneField('books.Book', related_name='intake_draft', null=True, blank=True,
                                on_delete=models.SET_NULL)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default=EXTRACTING)
    version = models.PositiveIntegerField(default=1)
    extracted = models.JSONField(default=dict, blank=True, help_text="LLM 원출력 + _unresolved 목록")
    warnings = models.JSONField(default=list, blank=True)
    files = models.JSONField(default=dict, blank=True, help_text="선택된 보도자료·표지와 입체 대안 경로")
    source_text = models.TextField(blank=True, help_text="로컬 추출 원문 (원문 대조·변경분 프롬프트용)")
    chat_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True, help_text="검수 메시지 ID (답장 대상 식별)")
    notion_page_id = models.CharField(max_length=100, blank=True)
    error = models.TextField(blank=True)

    def __str__(self):
        return f'초안 #{self.id} {self.book.title if self.book else ""} ({self.get_state_display()})'


class DraftRevision(BaseModel):
    draft = models.ForeignKey(BookDraft, related_name='revisions', on_delete=models.CASCADE)
    version = models.PositiveIntegerField()
    changes = models.JSONField(default=list, help_text="[{field, old, new}]")
    request_text = models.TextField(blank=True)
    requested_by = models.CharField(max_length=200, blank=True)
    reverted = models.BooleanField(default=False)


class PendingPatch(BaseModel):
    PROPOSED, APPLIED, CANCELLED, STALE = 'proposed', 'applied', 'cancelled', 'stale'
    STATUS_CHOICES = ((PROPOSED, '제안'), (APPLIED, '반영'), (CANCELLED, '취소'), (STALE, '만료'))

    draft = models.ForeignKey(BookDraft, related_name='patches', on_delete=models.CASCADE)
    base_version = models.PositiveIntegerField()
    changes = models.JSONField(default=list, help_text="[{field, new_value}]")
    questions = models.JSONField(default=list)
    request_text = models.TextField(blank=True)
    requested_by = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PROPOSED)
    message_id = models.BigIntegerField(null=True, blank=True)


class TelegramChat(BaseModel):
    """권한은 대화방 단위다. 등록된 가족 그룹과 관리자 1:1 방만 봇이 응답한다."""
    FAMILY, ADMIN = 'family', 'admin'
    KIND_CHOICES = ((FAMILY, '가족 그룹'), (ADMIN, '관리자 1:1'))

    chat_id = models.BigIntegerField(unique=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    title = models.CharField(max_length=200, blank=True)


class WorkerState(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField(default=None, null=True)

    @classmethod
    def get(cls, key, default=None):
        row = cls.objects.filter(key=key).first()
        return default if row is None else row.value

    @classmethod
    def put(cls, key, value):
        cls.objects.update_or_create(key=key, defaults={'value': value})
