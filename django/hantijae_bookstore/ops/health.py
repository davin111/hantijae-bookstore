"""운영 상태 판정 — /ops/status 페이지, 관리자 방 /status, 아침 알림이 함께 쓴다.

워커(intake.pipeline.run_iteration)가 약 1분마다 marketing.tasks._run_due 일정을 훑는다. 여기서는 DB만 읽어 작업마다
'이번 주기에 돌았나 · 실패 근거가 있나 · 새 기록이 쌓였나'를 판정한다(now를 받는 순수 함수).
「마지막 실행」 키는 작업을 시작하기 *전에* 적혀서 '시도했다'는 뜻일 뿐이다. 성공은 실패 카운터(*_fail_*),
marketing_error_<이름>(실패한 날짜), 새로 쌓인 행으로 본다.
화면에는 여기서 만든 문장만 나간다 — WorkerState 값을 통째로 내보내지 않는다(비밀처럼 보이는 키가 있다)."""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db.models import Max, Sum

from books.models import Book
from context.models import ContextEntry
from intake.models import BookDraft, FundingCampaign, IntakeSource, WorkerState
from marketing import instagram, kit, meta, social
from marketing.models import (BnkDay, Briefing, Draft, GrantCall, LoanSnapshot, Proposal, SalesSnapshot,
                              SelectionAnnouncement, Signal, SocialRun)
from marketing.selection_sources import SCANNERS
from marketing.timeutil import KST
from web.models import Notice, StoreClick

OK, CALM, WAIT, WARN, OFF = 'ok', 'calm', 'wait', 'warn', 'off'
LABELS = {OK: '정상', CALM: '새로 찾은 것 없음', WAIT: '첫 자동 실행 전', WARN: '살펴볼 것', OFF: '꺼짐'}
GRACE = timedelta(minutes=60)   # 새벽 LLM 작업(서평·계기)이 워커를 몇 분씩 붙잡아 뒤 작업이 밀린다
TICK_LIMIT = timedelta(minutes=30)   # 10분마다 도는 작업이 이만큼 비면 워커가 멈췄거나 밀린 것
FUND_LIMIT = timedelta(hours=7)      # 6시간마다
WEEKDAYS = '월화수목금토일'
REVIEW_SOURCES = ('naver_blog', 'naver_cafe', 'daum_blog', 'daum_cafe')


@dataclass
class Row:
    key: str
    label: str
    when: str               # '04:30' · '10분마다' · '상시'
    cadence: str = ''       # '매일' · '월요일'
    note: str = ''          # 무슨 일을 하나
    how: tuple = ()         # 직접 확인할 때 볼 키·명령(이름만)
    group: str = 'daily'    # daily: 정해진 시각 · always: 하루 내내
    state: str = OK
    last: str = '—'
    result: str = ''
    reason: str = ''        # 살펴볼 까닭

    @property
    def state_label(self):
        return LABELS[self.state]


@dataclass(frozen=True)
class Daily:
    """정해진 시각(KST). weekdays가 없으면 매일, start 전 예정은 따지지 않는다(새로 켠 매주 작업의 첫 실행 전)."""
    at: tuple
    weekdays: tuple = None
    start: date = None

    def _on(self, day):
        return (self.weekdays is None or day.weekday() in self.weekdays) and (self.start is None or day >= self.start)

    def last_due(self, local):
        for back in range(8):
            day = local.date() - timedelta(days=back)
            due = datetime.combine(day, time(*self.at), tzinfo=KST)
            if due <= local and self._on(day):
                return due
            if self.start and day < self.start:
                return None
        return None

    def next_due(self, local):
        for ahead in range(370):
            day = local.date() + timedelta(days=ahead)
            due = datetime.combine(day, time(*self.at), tzinfo=KST)
            if due > local and self._on(day):
                return due
        return None


class _Ctx:
    def __init__(self, now):
        self.now, self.local = now, now.astimezone(KST)
        self.today = self.local.date()
        self.state = dict(WorkerState.objects.values_list('key', 'value'))
        self.used_errors = set()

    def get(self, key, default=None):
        value = self.state.get(key)
        return default if value is None else value

    def recent_day(self, key):
        """키 값이 오늘이나 어제 날짜(YYYY-MM-DD)인가."""
        try:
            return date.fromisoformat(str(self.get(key, ''))[:10]) >= self.today - timedelta(days=1)
        except ValueError:
            return False

    def fails(self, keys):
        return [f'{k}={self.get(k)}' for k in keys if (self.get(k) or 0) > 0]

    def errors(self, *names):
        """marketing.tasks._guard가 남기는 실패한 날짜. 오늘·어제 것만."""
        self.used_errors.update(names)
        return [f'marketing_error_{n}({self.get(f"marketing_error_{n}")})' for n in names
                if self.recent_day(f'marketing_error_{n}')]


# ---- 표시 ----

def _md(d):
    return f'{d.month}/{d.day}'


def _when(d):
    """날짜·시각을 '10/3 06:07'처럼. 날짜 문자열이면 날짜만."""
    if not d:
        return '—'
    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d) if 'T' in d else date.fromisoformat(d)
        except ValueError:
            return '—'
    if isinstance(d, datetime):
        d = d.astimezone(KST)
        return f'{_md(d)} {d:%H:%M}'
    return _md(d)


def _due_text(due):
    return f'{_md(due)} ({WEEKDAYS[due.weekday()]}) {due:%H:%M}'


def _parse(iso):
    try:
        return datetime.fromisoformat(iso) if iso else None
    except (TypeError, ValueError):
        return None


def _verdict(row, problems, found, text):
    row.result = text
    if problems:
        row.state, row.reason = WARN, '; '.join(problems)
    else:
        row.state = OK if found else CALM


# ---- 일정 작업 공통 ----

def _scheduled(c, row, sched, key, judge, period=lambda due: due.date().isoformat()):
    """이번 주기에 돌았는지 본 뒤, 돌았으면 judge(c, row, since)로 실패 근거·결과를 본다.
    예정 시각이 지났어도 여유 시간(GRACE) 안이면 지난 주기 결과로 판단한다."""
    last = c.get(key) if key else None
    row.last = _when(last)
    due = sched.last_due(c.local)
    if due is None:
        row.state, row.result = WAIT, f'첫 실행 {_due_text(sched.next_due(c.local))}'
        return row
    since = due
    if key and last != period(due):
        prev = sched.last_due(due - timedelta(minutes=1))
        if c.local < due + GRACE and prev is not None and last == period(prev):
            since = prev
        elif c.local < due + GRACE:
            row.state, row.result = WAIT, f'첫 실행 {_due_text(due)}'
            return row
        else:
            row.state, row.reason = WARN, f'{_due_text(due)} 예정인데 돌지 않았어요(마지막 {row.last})'
            return row
    judge(c, row, since)
    return row


def _switch_off(row, why):
    row.state, row.result = OFF, why
    return row


# ---- 정해진 시각 작업 ----

def _signal_details(kind, since, sources):
    details = Signal.objects.filter(kind=kind, found_at__gte=since).values_list('detail', flat=True)
    return [d for d in details if (d or {}).get('source') in sources]


def _reviews(c, row, since):
    mine = _signal_details(Signal.REVIEW, since, REVIEW_SOURCES)
    real = sum(d.get('verdict') == 'review' for d in mine)
    _verdict(row, c.fails([f'review_fail_{s}' for s in REVIEW_SOURCES]) + c.errors('review'), real,
             f'기록한 글 {len(mine)}건(기준선 포함) · 서평 {real}건')


def _web(c, row, since):
    mine = _signal_details(Signal.REVIEW, since, ('web', 'youtube'))
    real = sum(d.get('verdict') == 'review' for d in mine)
    _verdict(row, c.fails(['review_fail_web', 'review_fail_youtube']) + c.errors('web'), real,
             f'찾은 기사·영상 {real}건')


def _meta_problems(c):
    problems = ['Meta 권한 오류(meta_auth_alert_day)'] if c.recent_day('meta_auth_alert_day') else []
    expires = instagram.expires_on()
    if expires - c.today <= timedelta(days=instagram.REMIND_BEFORE):
        problems.append(f'Meta 토큰 만료 {_md(expires)} — 다시 발급')
    return problems


def _instagram(c, row, since):
    mine = _signal_details(Signal.REVIEW, since, ('ig_tag',))
    real = sum(d.get('verdict') == 'review' for d in mine)
    _verdict(row, _meta_problems(c) + c.errors('instagram'), real,
             f'태그 글 {len(mine)}건 · 새 반응 {real}건 · 토큰 만료 {_md(instagram.expires_on())}')


def _partners(c, row, since):
    mine = _signal_details(Signal.REVIEW, since, ('ig_partner',))
    real = sum(d.get('verdict') == 'review' for d in mine)
    _verdict(row, _meta_problems(c), real, f'협력 계정 글 {len(mine)}건 · 새 반응 {real}건')


def _moments(c, row, since):
    n = Signal.objects.filter(kind=Signal.MOMENT, found_at__gte=since).count()
    _verdict(row, c.errors('moment'), n, f'새 계기 {n}개')


def _midweek(c, row, since):
    made = Proposal.objects.filter(kind=Proposal.NOW, created_at__gte=since)
    n, sent = made.count(), made.filter(sent_at__isnull=False).count()
    _verdict(row, c.errors('midweek', 'midweek_send'), n,
             f'만든 제안 {n}개 · 보냄 {sent}개 (7일 안 날짜가 잡힌 계기·2일 안 기념일만 대상이라 0개가 흔함)')


def _loans(c, row, since):
    n = LoanSnapshot.objects.filter(taken_at__gte=since).values('book').distinct().count()
    _verdict(row, c.errors('loan'), n, f'대출 기록 {n}권')


def _sales(c, row, since):
    n = SalesSnapshot.objects.filter(date=since.date()).count()
    target = Book.objects.filter(is_published=True, visible=True).exclude(isbn__isnull=True).exclude(isbn='').count()
    _verdict(row, c.fails(['marketing_sales_fail_streak']) + c.errors('sales', 'funding'), n,
             f'{n}권 / 판매 중인 공개 도서 {target}권')


def _selections(c, row, since):
    new = SelectionAnnouncement.objects.filter(scanned_at__gte=since)
    n, matched = new.count(), new.aggregate(m=Sum('matched'))['m'] or 0
    _verdict(row, c.fails([f'selection_fail_{sid}' for sid, _name, _scan in SCANNERS]) + c.errors('selection'),
             matched, f'새 공고 {n}건 · 한티재 책 {matched}권')


def _bnk(c, row, since):
    ok_on = c.get('bnk_ok_on')
    latest = BnkDay.objects.aggregate(d=Max('day'))['d']
    _verdict(row, c.fails(['bnk_fail_streak']) + c.errors('bnk'), ok_on == since.date().isoformat(),
             f'마지막 성공 {_when(ok_on)} · 읽은 마지막 판매일 {_when(latest)}(이틀 늦게 올라오는 게 정상)')


def _social(c, row, since):
    _token, accounts = social.config()
    stale = social.stale_accounts(accounts, c.now)
    runs = SocialRun.objects.filter(started_at__gte=since).order_by('started_at')
    done = runs.filter(state=SocialRun.SUCCEEDED).count()
    problems = ([f'오래 성공하지 못한 계정: {", ".join(stale)}'] if stale else []) + c.errors('social')
    _verdict(row, problems, done, f'실행 {runs.count()}번 · 성공 {done}번')


def _news(c, row, since):
    n = Signal.objects.filter(kind=Signal.NEWS, found_at__gte=since).count()
    _verdict(row, c.errors('news'), n, f'새 소식 {n}건')


def _grants(c, row, since):
    n = GrantCall.objects.filter(created_at__gte=since).count()
    _verdict(row, c.errors('grant', 'grant_send'), n, f'새 공고 {n}건')


def _brief_build(c, row, since):
    b = Briefing.objects.filter(week_start=since.date()).first()
    problems = c.errors('brief') + ([] if b else ['키는 적혔는데 브리핑이 없어요(만들다 멈췄을 수 있음)'])
    items = b.items.count() if b else 0
    _verdict(row, problems, items, f'항목 {items}개' if b else '')


def _brief_send(c, row, due):
    """보내기는 키가 없다 — 그 주 Briefing으로 본다. 21시까지 못 보내면 marketing_brief_missed에 그 주가 적힌다."""
    wk = due.date().isoformat()
    b = Briefing.objects.filter(week_start=due.date()).first()
    problems = c.errors('brief_send')
    if b and b.sent_at:
        row.last = _when(b.sent_at)
        _verdict(row, problems, True, f'보냄 {_when(b.sent_at)}')
        return row
    if c.get('marketing_brief_missed') == wk and (b is None or b.items.exists()):
        problems.append('21시까지 보내지 못했어요(marketing_brief_missed)')
    elif b and b.items.exists() and c.local >= due + GRACE:
        problems.append(f'{_due_text(due)}부터 보낼 차례인데 아직 못 보냈어요')
    if problems:
        _verdict(row, problems, False, '')
    elif b is None:
        row.state, row.result = CALM, '이번 주 브리핑 없음(만들기 줄 참고)'
    elif not b.items.exists():
        row.state, row.result = CALM, '후보가 없어 보낼 것 없음'
    else:
        row.state, row.result = WAIT, f'{_due_text(due)}부터 보냄'
    return row


def _monthly(c, row):
    first = c.today.replace(day=1)
    target = (first - timedelta(days=1)).strftime('%Y-%m')
    sent = c.get('bnk_last_monthly')
    row.last = sent or '—'
    problems = c.errors('monthly')
    if sent != target and (c.today.day >= 5 or c.get('monthly_late_noted') == target):
        problems.append(f'{target} 돌아보기를 아직 못 보냈어요(전산망 판매를 다 읽지 못했을 수 있음 · /bnk)')
    if problems:
        _verdict(row, problems, False, '')
    elif sent == target:
        row.state, row.result = OK, f'{target} 보냄'
    else:
        row.state, row.result = WAIT, f'{target}분: 3일 09:30 뒤, 전산망에서 한 달이 다 읽히면 보냄'
    return row


def _placements(c, row, since):
    posted = list(Draft.objects.filter(status=Draft.POSTED, posted_at__gte=c.now - timedelta(days=14))
                  .values_list('placements', flat=True))
    found = sum(bool(p) for p in posted)
    _verdict(row, c.errors('placement'), found, f'최근 2주 올린 초안 {len(posted)}개 중 {found}개 위치 찾음')


# ---- 하루 내내 ----

def _ticking(c, row, key, limit):
    """주기 작업: 마지막 확인(ISO 시각)이 limit보다 오래되면 살펴볼 것. 괜찮으면 None."""
    last = _parse(c.get(key))
    row.last = _when(last)
    if last is None:
        return f'{key}가 아직 없어요'
    if c.now - last > limit:
        return f'{int((c.now - last).total_seconds() // 60)}분째 확인이 없어요({key})'
    return None


def _drive(c, row):
    """폴더 수는 세지 않는다 — 기준선 등록 때 만든 행(BASELINE)이 섞여 있다. 실제로 만든 신간 초안과 실패한 자료를 본다."""
    week = c.now - timedelta(days=7)
    drafts = BookDraft.objects.filter(created_at__gte=week).count()
    last_draft = BookDraft.objects.aggregate(d=Max('created_at'))['d']
    failed = IntakeSource.objects.filter(status=IntakeSource.FAILED).count()
    late = _ticking(c, row, 'last_drive_scan', TICK_LIMIT)
    problems = ([late] if late else []) + ([f'처리에 실패한 자료 {failed}건(관리자 방 /retry 번호)'] if failed else [])
    _verdict(row, problems, drafts, f'최근 7일 신간 초안 {drafts}개 · 마지막 {_when(last_draft)}')


def _kits(c, row):
    failures = c.get(kit.FAILURES_KEY) or {}
    stuck = sum(1 for f in failures.values() if (f or {}).get('count', 0) >= kit.MAX_FAILURES)
    late = _ticking(c, row, 'marketing_last_kit_check', TICK_LIMIT)
    problems = ([late] if late else []) + c.errors('kit', 'kit_send')
    if stuck:
        problems.append(f'묶음을 {kit.MAX_FAILURES}번 못 만든 책 {stuck}권({kit.FAILURES_KEY})')
    week = Proposal.objects.filter(kind=Proposal.KIT, created_at__gte=c.now - timedelta(days=7)).count()
    last = Proposal.objects.filter(kind=Proposal.KIT).aggregate(d=Max('created_at'))['d']
    _verdict(row, problems, week, f'최근 7일 묶음 {week}개 · 마지막 {_when(last)}')


def _fund(c, row):
    late = _ticking(c, row, 'last_fund_scan', FUND_LIMIT)
    problems = ([late] if late else []) + (['펀딩 목록 읽기 실패(fund_error_day)'] if c.recent_day('fund_error_day') else [])
    ours = FundingCampaign.objects.filter(is_ours=True, ends_at__gt=c.now).count()
    _verdict(row, problems, ours, f'한티재 진행 중 펀딩 {ours}건')


def _notion(c, row):
    waiting = (Briefing.objects.filter(notion__state='pending').count()
               + Proposal.objects.filter(notion__state='pending').count())
    gave_up = (Briefing.objects.filter(notion__state='failed').count()
               + Proposal.objects.filter(notion__state='failed').count())
    row.last = '켜짐'
    _verdict(row, c.errors('notion', 'notion_flush', 'notion_read'), True,
             f'만들기를 기다리는 페이지 {waiting}개 · 지워져 멈춘 페이지 {gave_up}개')


def _context(c, row):
    live = ContextEntry.objects.filter(origin=ContextEntry.LIVE, source=ContextEntry.TELEGRAM)
    week = live.filter(at__gte=c.now - timedelta(days=7)).count()
    row.last = _when(live.aggregate(d=Max('at'))['d'])
    # 방이 조용하면 오래 비어 있을 수 있어 '늦음'은 따지지 않는다
    _verdict(row, [], week, f'최근 7일 {week}건')


def _clicks(c, row):
    week = StoreClick.objects.filter(created_at__gte=c.now - timedelta(days=7)).count()
    row.last = _when(StoreClick.objects.aggregate(d=Max('created_at'))['d'])
    _verdict(row, [], week, f'최근 7일 {week}회')


def _notices(c, row):
    posted = Notice.objects.filter(state=Notice.POSTED)
    ends = [_when(n.ends_at) for n in posted if n.ends_at]
    row.last = '게시 중' if posted else '없음'
    _verdict(row, [], posted.exists(),
             f'게시 중 {posted.count()}건' + (f' · {", ".join(ends)} 내려감' if ends else ''))


def _telegram(c, row):
    # 함수 안에서 불러온다: intake.bot(/status)이 이 모듈을 부르고, pipeline은 marketing 작업 전체를 불러온다
    from intake.pipeline import LAST_OUTAGE, OUTAGE, TG_ALERT_AFTER
    outage, last = c.get(OUTAGE), c.get(LAST_OUTAGE)
    parts = []
    if outage:
        parts.append(f'지금 다시 연결 중: {outage["fails"]}번 실패({_when(outage["since"])}부터)')
    parts.append(f'마지막 끊김 {_when(last["since"])}~{_when(last["until"])[-5:]}, {last["fails"]}번 실패'
                 if last else '끊김 기록 없음')
    if c.get('telegram_inflight') is not None:
        parts.append('처리 중인 업데이트 있음(telegram_inflight) — 오래 남아 있으면 멈춘 것')
    problems = ([f'텔레그램 수신이 {outage["fails"]}번 연속 실패 중({_when(outage["since"])}부터)']
                if outage and outage['fails'] >= TG_ALERT_AFTER else [])
    row.last = _when(outage['since']) if outage else '연결됨'
    _verdict(row, problems, True, ' · '.join(parts))


def _worker(c, row):
    """워커가 살아 있나. 따로 심장 박동 키는 없고, 10분마다 적히는 드라이브·묶음 확인 시각 중 최근 것을 본다."""
    beats = [t for t in (_parse(c.get('last_drive_scan')), _parse(c.get('marketing_last_kit_check'))) if t]
    if not beats:
        row.state, row.result = CALM, '판단할 키가 없어요(드라이브 감지·마케팅이 모두 꺼짐)'
        return
    last = max(beats)
    row.last = _when(last)
    quiet = c.now - last
    problems = [f'{int(quiet.total_seconds() // 60)}분째 소식이 없어요 — 워커가 멈췄을 수 있어요'
                f'(systemctl status hantijae-intake)'] if quiet > TICK_LIMIT else []
    _verdict(row, problems, True, f'마지막 바퀴 {_when(last)}')


# ---- 표 ----

def _marketing_on(c):
    return c.get('marketing_mode', 'off') != 'off'


def _daily_rows(c):
    m_on = _marketing_on(c)
    off = '마케팅 꺼짐(marketing_mode)'
    specs = [
        # (키, 이름, 설명, 확인할 키, 일정, 마지막 실행 키, 판정, 켜짐?, 꺼진 까닭)
        ('review', '독자 서평', '네이버·다음 블로그·카페, 책 1/7씩', ('marketing_last_review_scan', 'review_fail_*'),
         Daily((4, 30)), 'marketing_last_review_scan', _reviews, m_on, off),
        ('web', '구글 알리미 · 유튜브', '언급 찾기', ('marketing_last_web_scan', 'review_fail_web/youtube'),
         Daily((4, 40)), 'marketing_last_web_scan', _web, m_on, off),
        ('instagram', '인스타 태그 글', 'Meta API', ('marketing_last_instagram_scan', 'meta_auth_alert_day'),
         Daily((4, 50)), 'marketing_last_instagram_scan', _instagram, m_on and meta.ig_configured(),
         off if not m_on else 'Meta 설정 없음'),
        ('partner', '협력 계정', '책방·단체 인스타, 태그 글과 함께', ('marketing_last_instagram_scan(일요일)',),
         Daily((4, 50), weekdays=(instagram.PARTNER_WEEKDAY,), start=date(2026, 10, 4)), None, _partners,
         m_on and meta.ig_configured(), off if not m_on else 'Meta 설정 없음'),
        ('moment', '계기 잡기', '대화·노션·사진·링크에서 계기 추리기', ('moment_last_run', '/moment'),
         Daily((5, 0)), 'moment_last_run', _moments, m_on and c.get('moment_mode', 'off') != 'off',
         off if not m_on else 'moment_mode 꺼짐'),
        ('midweek', '주중 제안', '05:30 만들기 · 09:30~21:00 보내기', ('midweek_last_build',),
         Daily((5, 30), weekdays=(1, 2, 3, 4, 5)), 'midweek_last_build', _midweek,
         m_on and c.get('midweek_mode', 'off') != 'off', off if not m_on else 'midweek_mode 꺼짐'),
        ('loans', '도서관 대출', '정보나루 12달', ('marketing_last_loan_scan', '로그 loans:'),
         Daily((5, 40), weekdays=(5,), start=date(2026, 10, 3)), 'marketing_last_loan_scan', _loans, m_on, off),
        ('sales', '알라딘 판매 지수', '북펀드 진척 포함', ('marketing_last_sales_scan', 'marketing_sales_fail_streak'),
         Daily((6, 0)), 'marketing_last_sales_scan', _sales, m_on, off),
        ('selection', '공공 선정 공고', '출판진흥원·청소년 교양도서·학술원·사서추천',
         ('marketing_last_selection_scan', 'selection_fail_*'), Daily((6, 10)), 'marketing_last_selection_scan',
         _selections, m_on, off),
        ('bnk', '출판유통통합전산망 판매', '판매는 이틀 늦게 올라옴', ('bnk_last_run', 'bnk_ok_on', '/bnk'),
         Daily((6, 20)), 'bnk_last_run', _bnk, m_on and c.get('bnk_mode', 'off') == 'on',
         off if not m_on else 'bnk_mode 꺼짐'),
        ('social', '운영진 개인 SNS', '페북 매일 · 인스타 주 1, Apify', ('marketing_social_daily', 'marketing_social_ok'),
         Daily((6, 20)), 'marketing_social_daily', _social, m_on and c.get(social.SWITCH_KEY) == 'on',
         off if not m_on else 'marketing_social 꺼짐'),
        ('news', '저자 소식', '구글 뉴스 · 감시어', ('marketing_last_news_scan',),
         Daily((6, 30), weekdays=(0,), start=date(2026, 10, 4)), 'marketing_last_news_scan', _news, m_on, off),
        ('grant', '지원사업 공고', 'AI 판단 하루 최대 3건', ('grant_last_scan', '/grant'),
         Daily((6, 40)), 'grant_last_scan', _grants, m_on and c.get('grant_mode', 'off') != 'off',
         off if not m_on else 'grant_mode 꺼짐'),
        ('brief_build', '월요일 브리핑 만들기', '', ('marketing_last_brief_week',),
         Daily((7, 0), weekdays=(0,), start=date(2026, 10, 4)), 'marketing_last_brief_week', _brief_build, m_on, off),
        ('placement', '게시 위치 찾기', '[올렸어요] 초안이 어디 올라갔나', ('marketing_last_placement_scan',),
         Daily((12, 0)), 'marketing_last_placement_scan', _placements, m_on, off),
    ]
    rows = []
    for key, label, note, how, sched, last_key, judge, on, why in specs:
        row = Row(key, label, f'{sched.at[0]:02d}:{sched.at[1]:02d}', _cadence(sched), note, how)
        rows.append(_scheduled(c, row, sched, last_key, judge) if on else _switch_off(row, why))

    send = Row('brief_send', '브리핑 보내기', '09:30', '월요일', '검수 방, 21시까지 못 보내면 관리자에게',
               ('marketing_brief_missed',))
    due = Daily((9, 30), weekdays=(0,)).last_due(c.local)
    rows.append(_brief_send(c, send, due) if m_on else _switch_off(send, off))
    monthly = Row('monthly', '월간 돌아보기', '09:30', '매달 3일~', '전산망 한 달이 다 읽히면',
                  ('bnk_last_monthly', '/bnk monthly'))
    monthly_on = m_on and c.get('bnk_mode', 'off') == 'on' and c.get('monthly_mode', 'off') != 'off'
    rows.append(_monthly(c, monthly) if monthly_on else _switch_off(monthly, 'bnk_mode·monthly_mode 꺼짐'))
    rows.sort(key=lambda r: r.when)
    return rows


def _cadence(sched):
    if sched.weekdays is None:
        return '매일'
    if len(sched.weekdays) == 1:
        return WEEKDAYS[sched.weekdays[0]] + '요일'
    return f'{WEEKDAYS[sched.weekdays[0]]}~{WEEKDAYS[sched.weekdays[-1]]}'


def _always_rows(c):
    m_on = _marketing_on(c)
    rows = []

    def add(key, label, when, note, how, fn, on=True, why=''):
        row = Row(key, label, when, '', note, how, group='always')
        if on:
            fn(c, row)
        else:
            _switch_off(row, why)
        rows.append(row)

    add('worker', '워커', '약 1분마다', '텔레그램 수신과 모든 일정의 바탕', ('systemctl status hantijae-intake',), _worker)
    add('telegram', '텔레그램 수신', '매 바퀴', '연속 3번 실패하면 관리자 방에 알림',
        ('telegram_poll_outage', 'telegram_poll_last_outage'), _telegram)
    add('context', '검수 방 대화 기록', '상시', '가린 글만, 90일', ('context_record', '/ctx'), _context,
        bool(c.get('context_record', False)), 'context_record 꺼짐')
    purge = Row('purge', '대화 기록 정리', '하루 한 번', '', '90일 넘은 기록 지우기', ('last_context_purge',), group='always')
    rows.append(_scheduled(c, purge, Daily((0, 0)), 'last_context_purge', lambda _c, r, _since: _verdict(r, [], True, '오늘 돎')))
    add('drive', '드라이브 신간 감지', '10분마다', '보도자료 폴더 → 신간 초안', ('last_drive_scan', '/drive'), _drive,
        bool(c.get('drive_autoscan', False)), 'drive_autoscan 꺼짐')
    add('kit', '신간 홍보 묶음', '10분마다', '08~21시에 보냄, 하루 2장까지', ('marketing_last_kit_check', '/mk'), _kits,
        m_on, '마케팅 꺼짐(marketing_mode)')
    add('fund', '북펀드 감지', '6시간마다', '알라딘 북펀드·텀블벅', ('last_fund_scan', 'fund_error_day', '/fund'), _fund,
        bool(c.get('fund_autoscan', True)), 'fund_autoscan 꺼짐')
    add('notion', '노션 글 모음', '매 바퀴', '브리핑·초안을 노션에도', ('marketing_notion',), _notion,
        m_on and c.get('marketing_notion') == 'on', 'marketing_notion 꺼짐')
    add('notice', '사이트 알림 띠', '상시', '', ('/notice',), _notices)
    add('clicks', '서점 버튼 클릭', '요청 때', '사이트 /go/, IP·쿠키 저장 안 함', (), _clicks)
    return rows


def _other_errors(c):
    """작업 줄에 묶이지 않은 marketing_error_* (예: run_due) — 놓치지 않게 따로 한 줄."""
    names = sorted(k[len('marketing_error_'):] for k in c.state if k.startswith('marketing_error_'))
    left = [f'marketing_error_{n}({c.get("marketing_error_" + n)})' for n in names
            if n not in c.used_errors and c.recent_day(f'marketing_error_{n}')]
    if not left:
        return []
    row = Row('errors', '그 밖의 마케팅 오류', '—', '', '작업 줄에 묶이지 않은 오류 키', (), group='always')
    _verdict(row, left, False, '')
    return [row]


def evaluate(now):
    c = _Ctx(now)
    rows = _daily_rows(c) + _always_rows(c)
    return rows + _other_errors(c)


def watch(rows):
    return [r for r in rows if r.state == WARN]


def summary_lines(rows):
    """관리자 방 /status·아침 알림용: 살펴볼 것만. 없으면 한 줄."""
    warn = watch(rows)
    if not warn:
        off = sum(r.state == OFF for r in rows)
        return [f'✅ 모두 정상 (작업 {len(rows) - off}개' + (f', 꺼짐 {off}개)' if off else ')')]
    return [f'⚠️ 살펴볼 것 {len(warn)}개'] + [f'· {r.label}: {r.reason}' for r in warn]
