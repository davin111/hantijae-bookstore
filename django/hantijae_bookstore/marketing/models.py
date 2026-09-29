from datetime import date

from django.db import models

from books.models import Book
from core.models import BaseModel


class BookProfile(BaseModel):
    book = models.OneToOneField(Book, related_name='marketing', on_delete=models.CASCADE)
    aladin_item_id = models.CharField(max_length=20, blank=True)
    quiet_until = models.DateField(null=True, blank=True, help_text='이 날짜까지 홍보 제안을 하지 않음')
    quiet_reason = models.CharField(max_length=200, blank=True, help_text='관리자만 봄')

    def is_quiet(self, today):
        return bool(self.quiet_until and self.quiet_until >= today)


class SalesSnapshot(models.Model):
    book = models.ForeignKey(Book, related_name='sales_snapshots', on_delete=models.CASCADE)
    date = models.DateField()
    sales_point = models.PositiveIntegerField()
    short_reviews = models.PositiveIntegerField(default=0)
    reviews = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('book', 'date')
        ordering = ('-date',)


class HookDate(BaseModel):
    name = models.CharField(max_length=100)
    month = models.PositiveSmallIntegerField()
    day = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField(null=True, blank=True, help_text='비우면 매년')
    books = models.ManyToManyField(Book, blank=True, related_name='hook_dates')
    memorial = models.BooleanField(default=False, help_text='추모 성격: 판매 권유 금지')
    note = models.CharField(max_length=300, blank=True)
    source_url = models.URLField(max_length=500, blank=True)

    def next_on(self, today):
        """today 이후(당일 포함) 가장 가까운 날. 연도가 정해져 있으면 그날만."""
        years = [self.year] if self.year else range(today.year, today.year + 5)
        for y in years:
            try:
                d = date(y, self.month, self.day)
            except ValueError:  # 윤년이 아닌 해의 2월 29일
                continue
            if d >= today:
                return d
        return None


class Signal(models.Model):
    NEWS, MOMENT = 'news', 'moment'
    kind = models.CharField(max_length=20, choices=((NEWS, '저자 소식'), (MOMENT, '대화 속 계기')))
    key = models.CharField(max_length=200, unique=True)
    book = models.ForeignKey(Book, null=True, blank=True, on_delete=models.SET_NULL)
    title = models.CharField(max_length=500)
    detail = models.JSONField(default=dict, blank=True)
    url = models.URLField(max_length=1000, blank=True)
    happens_on = models.DateField(null=True, blank=True)
    found_at = models.DateTimeField(auto_now_add=True)
    relevant = models.BooleanField(default=False)
    sensitive = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)


class SignalEvidence(models.Model):
    """계기(kind=moment)의 근거 기록. 기록이 90일 정리로 지워지면 연결도 같이 지워진다.
    JSON 목록이 아니라 모델인 이유: '이 기록을 근거로 한 계기'를 SQLite(테스트)에서도 조회할 수 있어야 한다."""
    signal = models.ForeignKey(Signal, related_name='evidence', on_delete=models.CASCADE)
    entry = models.ForeignKey('context.ContextEntry', related_name='+', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('signal', 'entry')


class MomentScan(models.Model):
    """이 기록의 이 버전(changed_at)까지 계기 추출에 넣었다는 표시. 조각 단위로 일부만 성공해도 빠뜨리거나 두 번 넣지 않게."""
    entry = models.OneToOneField('context.ContextEntry', related_name='+', on_delete=models.CASCADE)
    changed_at = models.DateTimeField()


class Briefing(models.Model):
    week_start = models.DateField(unique=True)
    measure = models.CharField(max_length=300, blank=True)
    chat_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    mode = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Proposal(BaseModel):
    KIT, BRIEF_ITEM, NOW = 'kit', 'brief_item', 'now'
    PROPOSED, SHOWN, ACTED, SKIPPED = 'proposed', 'shown', 'acted', 'skipped'
    kind = models.CharField(max_length=20, choices=((KIT, '신간 홍보 묶음'), (BRIEF_ITEM, '브리핑 항목'), (NOW, '주중 제안')))
    book = models.ForeignKey(Book, null=True, blank=True, related_name='marketing_proposals', on_delete=models.CASCADE)
    signal = models.ForeignKey(Signal, null=True, blank=True, on_delete=models.SET_NULL)
    briefing = models.ForeignKey(Briefing, null=True, blank=True, related_name='items', on_delete=models.CASCADE)
    candidate_key = models.CharField(max_length=200, blank=True)
    headline = models.CharField(max_length=300)
    reason = models.TextField(blank=True)
    caution = models.TextField(blank=True)
    rank = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=20, default=PROPOSED)
    extra = models.JSONField(default=dict, blank=True)
    chat_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)


class Draft(BaseModel):
    BLOG, INSTAGRAM, LINKS, SHORT, LETTER = 'blog', 'instagram', 'links', 'short', 'letter'
    CHANNEL_CHOICES = ((BLOG, '블로그 글'), (INSTAGRAM, '인스타 글'), (LINKS, '서점 링크 공지'),
                       (SHORT, '짧은 소개'), (LETTER, '보낼 글'))
    DRAFT, POSTED, SKIPPED = 'draft', 'posted', 'skipped'
    proposal = models.ForeignKey(Proposal, related_name='drafts', on_delete=models.CASCADE)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    title = models.CharField(max_length=300, blank=True)
    body = models.TextField()
    version = models.PositiveSmallIntegerField(default=1)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, default=DRAFT)
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.CharField(max_length=100, blank=True)
    chat_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True)

    @property
    def label(self):
        return dict(self.CHANNEL_CHOICES)[self.channel]


class DraftMessage(models.Model):
    """초안을 보낸 메시지마다 한 줄. [글 보기]를 여러 번 눌러도 어느 사본에 답장하든 그 초안을 찾는다."""
    draft = models.ForeignKey(Draft, related_name='messages', on_delete=models.CASCADE)
    chat_id = models.BigIntegerField()
    message_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('chat_id', 'message_id')


class CopyNote(models.Model):
    draft = models.ForeignKey(Draft, related_name='notes', on_delete=models.CASCADE)
    text = models.TextField()
    by = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class WatchQuery(BaseModel):
    query = models.CharField(max_length=200, unique=True)
    book = models.ForeignKey(Book, null=True, blank=True, on_delete=models.SET_NULL)
    active = models.BooleanField(default=True)


class FundingSnapshot(models.Model):
    campaign = models.ForeignKey('intake.FundingCampaign', related_name='snapshots', on_delete=models.CASCADE)
    date = models.DateField()
    amount = models.PositiveIntegerField()
    goal = models.PositiveIntegerField(default=0)
    books = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('campaign', 'date')

    @property
    def percent(self):
        return round(self.amount * 100 / self.goal) if self.goal else 0
