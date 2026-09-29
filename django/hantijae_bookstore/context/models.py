"""맥락 기록: 운영진 대화 같은 한티재 안쪽 맥락을 가린 채 모은다. 원문은 저장하지 않는다."""
from django.db import models

from core.models import BaseModel

ROLE_CHOICES = (('운영진A', '운영진A(대표)'), ('운영진B', '운영진B'), ('운영진C', '운영진C(편집장)'),
                ('관리자', '관리자'), ('봇', '봇'), ('참여자', '참여자'))
DEFAULT_ROLE = '참여자'
IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp')
# /잊어·관리자 '잊기'가 비우는 칸. 키와 시각은 남겨 같은 메시지가 되살아나지 않게 한다
FORGET_FIELDS = {'forgotten': True, 'text': '', 'media_name': '', 'file_id': '', 'redactions': {}, 'media_text': '',
                 'heading': ''}


class ContextEntry(BaseModel):
    """기록 한 줄. 일반 그룹은 메시지 번호가 계정마다 따로라 실시간(tg:)과 내보내기(tgx:) 번호 공간을 나눈다.

    /잊어 로 지운 기록은 내용만 비우고 키를 남긴다(forgotten) — 같은 업데이트를 다시 받거나 내보내기를 다시 넣어도
    되살아나지 않게. 기록을 읽는 쪽은 forgotten=False 만 쓴다.
    """
    TELEGRAM, NOTION = 'telegram', 'notion'
    SOURCE_CHOICES = ((TELEGRAM, '텔레그램'), (NOTION, '노션'))
    LIVE, EXPORT = 'live', 'export'
    ORIGIN_CHOICES = ((LIVE, '실시간'), (EXPORT, '내보내기 가져오기'))

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=TELEGRAM)
    origin = models.CharField(max_length=20, choices=ORIGIN_CHOICES, default=LIVE)
    key = models.CharField(max_length=200, unique=True)
    chat_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True)
    reply_to_id = models.BigIntegerField(null=True, blank=True)
    reply_to_bot = models.BooleanField(default=False)
    at = models.DateTimeField(db_index=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    author_id = models.BigIntegerField(null=True, blank=True)
    author_name = models.CharField(max_length=100, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=DEFAULT_ROLE)
    text = models.TextField(blank=True, help_text='가린 본문만 저장한다')
    redactions = models.JSONField(default=dict, blank=True, help_text='규칙별 가림 건수')
    media = models.CharField(max_length=20, blank=True)
    media_name = models.CharField(max_length=200, blank=True)
    file_id = models.CharField(max_length=200, blank=True)
    forwarded = models.BooleanField(default=False)
    forgotten = models.BooleanField(default=False, help_text='운영진이 지워 달라고 한 기록(내용 비움)')
    heading = models.CharField(max_length=200, blank=True, help_text='노션 구역: 『페이지 제목』 · 구역 제목')
    media_text = models.TextField(blank=True, help_text='사진에서 읽은 글(가림 적용). 첫 줄에 [포스터] 같은 종류')
    media_read_at = models.DateTimeField(null=True, blank=True, help_text='사진을 읽은 시각(글자 없는 사진도)')

    class Meta:
        ordering = ['at']
        indexes = [models.Index(fields=['chat_id', 'at'])]
        verbose_name = verbose_name_plural = '대화 기록'

    def __str__(self):
        return f'{self.at:%Y-%m-%d %H:%M} {self.role} {self.text[:30]}'

    @property
    def changed_at(self):
        """기록이 마지막으로 바뀐 때(들어옴·수정·사진 읽음). 계기 추출이 이 버전을 봤는지 비교하는 기준."""
        return max(t for t in (self.created_at, self.edited_at, self.media_read_at) if t)

    @property
    def is_image(self):
        return self.media == 'photo' or (self.media == 'document' and self.media_name.lower().endswith(IMAGE_EXTS))


class Participant(BaseModel):
    """텔레그램 사람 → 역할. 저장·삭제하면 이미 쌓인 기록의 역할도 다시 맞춘다."""
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    telegram_user_id = models.BigIntegerField(null=True, blank=True, unique=True)
    aliases = models.CharField(max_length=300, blank=True, help_text='내보내기 파일·텔레그램에 보이는 이름, 쉼표로 구분')

    class Meta:
        verbose_name = verbose_name_plural = '대화 참여자 역할'

    def __str__(self):
        return f'{self.role} {self.aliases or self.telegram_user_id}'

    def names(self):
        return [a.strip() for a in self.aliases.split(',') if a.strip()]

    def save(self, *args, **kwargs):
        old = Participant.objects.filter(pk=self.pk).first() if self.pk else None
        super().save(*args, **kwargs)
        from context.roles import refresh_roles   # roles 가 models 를 import 한다
        for p in (old, self):
            if p:
                refresh_roles(p)

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        from context.roles import refresh_roles
        refresh_roles(self)
        return result
