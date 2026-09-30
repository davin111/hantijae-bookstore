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
    NEWS, SELECTION, SOCIAL, MOMENT, REVIEW = 'news', 'selection', 'social', 'moment', 'review'
    kind = models.CharField(max_length=20, choices=((NEWS, '저자 소식'), (SELECTION, '공공 선정'), (SOCIAL, '운영진 SNS'),
                                                    (MOMENT, '대화 속 계기'), (REVIEW, '독자 서평')))
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
    placements = models.JSONField(default=list, blank=True,
                                  help_text='[올렸어요] 뒤 봇이 찾은 실제 게시 위치: kind·label·url·id·at (placements.py)')

    # 운영진에게 보이는 이름. 선택지(CHANNEL_CHOICES)를 바꾸면 마이그레이션이 생겨서 표시만 따로 둔다
    DISPLAY = {BLOG: '네이버 블로그 글'}

    @property
    def label(self):
        return self.DISPLAY.get(self.channel) or dict(self.CHANNEL_CHOICES)[self.channel]


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
    narrow = models.CharField(max_length=300, blank=True,
                              help_text='검색어에 덧붙이는 조건(동명이인 거르기). 예: (가수 OR 노래 OR 한티재)')
    narrowed_at = models.DateTimeField(null=True, blank=True,
                                       help_text='조건을 정한 때(자동·/watch). 비어 있으면 다음 수집 때 자동으로 고른다')


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


class SelectionAnnouncement(models.Model):
    """공공 선정 발표 한 건(게시글 또는 목록 한 줄). 한 번 본 발표는 다시 받지 않으려고 모두 적는다."""
    key = models.CharField(max_length=200, unique=True)
    source = models.CharField(max_length=20)
    label = models.CharField(max_length=200)
    url = models.URLField(max_length=1000)
    posted_on = models.DateField(null=True, blank=True)
    withdrawal = models.BooleanField(default=False, help_text='철회·취소 공고')
    matched = models.PositiveSmallIntegerField(default=0, help_text='찾은 한티재 책 수')
    scanned_at = models.DateTimeField(auto_now_add=True)


class SocialRun(models.Model):
    """Apify 실행 한 번. Apify를 부르기 전에 먼저 만든다(워커가 죽어도 같은 시도를 되풀이하지 않게)."""
    FACEBOOK, INSTAGRAM = 'facebook', 'instagram'
    NORMAL, FIRST, DEEP, MANUAL = 'normal', 'first', 'deep', 'manual'
    STARTING, RUNNING, SUCCEEDED, FAILED, SKIPPED = 'starting', 'running', 'succeeded', 'failed', 'skipped'
    platform = models.CharField(max_length=20, choices=((FACEBOOK, '페이스북'), (INSTAGRAM, '인스타그램')))
    purpose = models.CharField(max_length=10, default=NORMAL, help_text='normal·first(첫 실행)·deep(틈 보충)·manual')
    accounts = models.JSONField(default=list, blank=True, help_text='역할 키 목록')
    limit = models.PositiveSmallIntegerField(default=5, help_text='계정당 글 수')
    apify_run_id = models.CharField(max_length=50, blank=True)
    dataset_id = models.CharField(max_length=50, blank=True)
    state = models.CharField(max_length=10, default=STARTING)
    apify_status = models.CharField(max_length=20, blank=True)
    error = models.CharField(max_length=300, blank=True)
    cap_usd = models.DecimalField(max_digits=6, decimal_places=3)
    cost_usd = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    stats = models.JSONField(default=dict, blank=True, help_text='계정별 items·valid·errors·new·known·reached·gap·status')
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-started_at',)


class SocialPost(models.Model):
    """운영진 개인 계정의 글 하나. 계정 주소는 저장하지 않고, 본문은 보관 기간이 지나면 지운다(social.prune)."""
    platform = models.CharField(max_length=20)
    account = models.CharField(max_length=20, help_text='역할 키(editor·ceo)')
    post_id = models.CharField(max_length=100)
    url = models.URLField(max_length=1000)
    posted_at = models.DateTimeField()
    text = models.TextField(blank=True, help_text='본인이 쓴 말')
    shared = models.JSONField(default=dict, blank=True, help_text='공유 원문: url, text, author, posted_at')
    link = models.JSONField(default=dict, blank=True, help_text='외부 링크: url, title, source')
    group_key = models.CharField(max_length=300, blank=True, db_index=True)
    first_run = models.ForeignKey(SocialRun, null=True, blank=True, related_name='+', on_delete=models.SET_NULL)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()
    judged_at = models.DateTimeField(null=True, blank=True)
    verdict = models.JSONField(default=dict, blank=True)
    signal = models.ForeignKey(Signal, null=True, blank=True, related_name='social_posts', on_delete=models.SET_NULL)
    text_cleared_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('platform', 'post_id')

    def full_text(self):
        return '\n'.join(t for t in (self.text, self.shared.get('text', ''), self.link.get('title', '')) if t)


class GrantCall(models.Model):
    """진흥원 지원사업 공고 한 건(게시글). 한 번 본 글은 다시 판단하지 않으려고 모두 적는다(grants.py)."""
    IGNORED, OLD, PENDING, SKIPPED_LLM = 'ignored', 'old', 'pending', 'skipped_llm'
    READY, ANNOUNCED, APPLYING, PASSED = 'ready', 'announced', 'applying', 'passed'
    OPEN = (ANNOUNCED, APPLYING)
    key = models.CharField(max_length=200, unique=True)
    title = models.CharField(max_length=300)
    url = models.URLField(max_length=1000)
    posted_on = models.DateField()
    state = models.CharField(max_length=20)
    tries = models.PositiveSmallIntegerField(default=0, help_text='LLM 판단 실패 횟수(3번이면 건너뜀)')
    verdict = models.JSONField(default=dict, blank=True)
    apply_until = models.DateField(null=True, blank=True, help_text='원문과 대조해 확인한 마감일만')
    preview_at = models.DateTimeField(null=True, blank=True, help_text='관리자 1:1 미리보기를 보낸 시각')
    chat_id = models.BigIntegerField(null=True, blank=True)
    message_id = models.BigIntegerField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True, help_text='검수 방에 카드를 보낸 시각')
    decided_by = models.CharField(max_length=100, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True, help_text='마감 이틀 전 알림을 보낸 시각')
    reminder_message_id = models.BigIntegerField(null=True, blank=True, help_text='그 알림 메시지(답장을 받으려고)')
    created_at = models.DateTimeField(auto_now_add=True)


class BnkSale(models.Model):
    """출판유통통합전산망 판매: 책 하나 × 하루 하나. 약 2일 늦게 들어와서 매일 최근 7일을 날짜째 바꿔 넣는다(bnk_sales)."""
    day = models.DateField(db_index=True)
    isbn = models.CharField(max_length=13)
    book = models.ForeignKey(Book, null=True, blank=True, related_name='bnk_sales', on_delete=models.SET_NULL)
    title = models.CharField(max_length=300)
    kyobo = models.IntegerField(default=0)
    yes24 = models.IntegerField(default=0)
    aladin = models.IntegerField(default=0)
    ypbooks = models.IntegerField(default=0, help_text='영풍문고')
    local = models.IntegerField(default=0, help_text='지역서점')
    total = models.IntegerField(default=0, help_text='반품이 많으면 음수일 수 있다')
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('day', 'isbn')


class BnkDay(models.Model):
    """전산망 하루를 마지막으로 읽은 날. 약 2일 늦게 들어오므로 월간 요약은 그 달 모든 날이 '그날+2일' 뒤에 읽혔을 때만 보낸다."""
    day = models.DateField(unique=True)
    read_on = models.DateField()
