"""운영진 개인 SNS 수집(Apify): 일정·실행 상태·저장·틈·건강 검사·보관. 글 해석은 social_judge가 한다.
설계(로컬 문서): .claude/docs/specs/2026-09-30-personal-social-collector-design.md

빈 결과를 '새 글 없음'으로 오인하지 않으려고 매번 최근 몇 건을 일부러 겹치게 받는다:
- 0건·오류만·필수 필드 빠짐 → 그 계정은 실패
- 받은 글이 모두 처음 보는 글이고 한도만큼 찼다 → 틈(사이에 놓친 글이 있을 수 있음) → 20건으로 한 번 더"""
import json
import logging
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Max

from intake.models import WorkerState
from marketing import social_judge
from marketing.apify import FINAL, Apify, ApifyAuthError, ApifyError
from marketing.models import SocialPost, SocialRun
from marketing.social_parse import FACEBOOK, INSTAGRAM, parse_facebook, parse_instagram
from marketing.timeutil import KST, kst_now, week_start

log = logging.getLogger('intake')
OK_KEY = 'marketing_social_ok'          # {"facebook:editor": ISO 시각} — 정상으로 받은 계정만 갱신한다
SWITCH_KEY = 'marketing_social'         # 'on'일 때만 돈다(배포 직후엔 꺼져 있음)
ALERTS_KEY = 'marketing_social_alerts'  # {알림 종류: 도장} — 같은 종류는 기간·날짜마다 한 번
ON_SINCE_KEY = 'marketing_social_on_since'  # 켠 시각(한 번도 성공 못 한 계정의 '오래됨' 기준)
DAILY_KEY = 'marketing_social_daily'
BASELINE_DAYS = 30                      # 이보다 오래된 글은 '본 글'로만 두고 판정하지 않는다

ACTORS = {FACEBOOK: 'apify~facebook-posts-scraper', INSTAGRAM: 'apify~instagram-post-scraper'}
PLATFORM_KO = {FACEBOOK: '페이스북', INSTAGRAM: '인스타'}
PERIOD_KO = {FACEBOOK: '오늘', INSTAGRAM: '이번 주'}
STATUS_KO = {'empty': '0건', 'error': '오류만', 'malformed': '형식 바뀜'}
SOCIAL_AT = (6, 20)                     # 공공 선정(06:10) 다음, 저자 소식(06:30)·브리핑(07:00) 앞
NORMAL_LIMIT, DEEP_LIMIT = 5, 20        # 계정당 글 수: 평소 / 첫 실행·틈 보충
CAPS = {(FACEBOOK, False): Decimal('0.15'), (FACEBOOK, True): Decimal('0.40'),
        (INSTAGRAM, False): Decimal('0.10'), (INSTAGRAM, True): Decimal('0.20')}  # (플랫폼, 20건 실행?) → 상한
RUN_TIMEOUT, WAIT_SECONDS, GIVE_UP = 180, 45, timedelta(minutes=15)
MAX_ATTEMPTS = {FACEBOOK: 2, INSTAGRAM: 3}
RETRY_GAP = {FACEBOOK: timedelta(hours=2), INSTAGRAM: timedelta(hours=20)}
MONTHLY_BUDGET_USD = Decimal('3.00')
STALE_AFTER = {FACEBOOK: timedelta(days=3), INSTAGRAM: timedelta(days=10)}
KEEP_IRRELEVANT, KEEP_RELEVANT, KEEP_ROWS = timedelta(days=14), timedelta(days=90), timedelta(days=180)
REGULAR = (SocialRun.NORMAL, SocialRun.FIRST)


def config():
    """(Apify 토큰, 계정 목록). 계정 JSON이 깨졌으면 빈 목록."""
    cfg = getattr(settings, 'MARKETING', {})
    try:
        accounts = json.loads(cfg.get('SOCIAL_ACCOUNTS') or '[]')
    except ValueError:
        accounts = []
    return cfg.get('APIFY_TOKEN', ''), [a for a in accounts if isinstance(a, dict) and a.get('role')]


def labels(accounts):
    return {a['role']: a.get('label') or a['role'] for a in accounts}


def account_status(c):
    if c['items'] == 0:
        return 'empty'
    if c['valid'] == 0 and c['errors']:
        return 'error'
    if c['valid'] * 2 < c['items']:
        return 'malformed'
    return 'ok'


def mark_ok(platform, role, now):
    ok = dict(WorkerState.get(OK_KEY) or {})
    ok[f'{platform}:{role}'] = now.isoformat()
    WorkerState.put(OK_KEY, ok)


def _save(p, run, now):
    post = SocialPost.objects.create(platform=p.platform, account=p.account, post_id=p.post_id, url=p.url[:1000],
                                     posted_at=p.posted_at, text=p.text, shared=p.shared, link=p.link,
                                     first_run=run, first_seen=now, last_seen=now)
    post.group_key = social_judge.assign_group(post)[:300]
    fields = ['group_key']
    if p.posted_at < now - timedelta(days=BASELINE_DAYS):
        post.judged_at, post.verdict = now, {'baseline': True}
        fields += ['judged_at', 'verdict']
    post.save(update_fields=fields)
    return post


def store(run, items, accounts, now):
    """결과를 글로 저장하고 계정별 통계·틈을 적는다. 새로 본 글 목록을 돌려준다."""
    parse = parse_facebook if run.platform == FACEBOOK else parse_instagram
    parsed = parse(items, accounts)
    stats, new = {}, []
    for role in run.accounts:
        c = parsed.counts.get(role) or {'items': 0, 'valid': 0, 'errors': 0}
        mine = list({p.post_id: p for p in parsed.posts if p.account == role}.values())  # 한 결과 안 중복 제거
        newest = SocialPost.objects.filter(platform=run.platform, account=role).aggregate(m=Max('posted_at'))['m']
        # 같은 글이 두 운영진 결과에 함께 올 수 있다(공동 글·태그) → 계정과 상관없이 이미 저장한 글은 '아는 글'
        known = set(SocialPost.objects.filter(platform=run.platform, post_id__in=[p.post_id for p in mine])
                    .values_list('post_id', flat=True))
        status = account_status(c)
        reached = (newest is None or bool(known) or len(mine) < run.limit
                   or (bool(mine) and min(p.posted_at for p in mine) <= newest))
        made = [_save(p, run, now) for p in mine if p.post_id not in known]
        SocialPost.objects.filter(platform=run.platform, post_id__in=known).update(last_seen=now)
        new += made
        stats[role] = {**c, 'new': len(made), 'known': len(known), 'reached': reached,
                       'gap': status == 'ok' and not reached, 'status': status}
        if status == 'ok':
            mark_ok(run.platform, role, now)
    run.stats, run.state, run.finished_at = stats, SocialRun.SUCCEEDED, now
    run.save(update_fields=['stats', 'state', 'finished_at'])
    return new


# ---- 일정 ----

def period_start(platform, now):
    """페북은 그날 0시, 인스타는 그 주 월요일 0시(KST)."""
    day = kst_now(now).date()
    return datetime.combine(day if platform == FACEBOOK else week_start(day), time.min, tzinfo=KST)


def _period_runs(platform, now):
    return list(SocialRun.objects.filter(platform=platform, started_at__gte=period_start(platform, now))
                .order_by('started_at', 'id'))


def month_spent(now):
    """이번 달(KST) 쓴 돈. 실제 청구액을 모르면(진행 중 등) 상한으로 센다."""
    start = datetime.combine(kst_now(now).date().replace(day=1), time.min, tzinfo=KST)
    total = Decimal('0')
    for run in SocialRun.objects.filter(started_at__gte=start).exclude(state=SocialRun.SKIPPED):
        total += run.cost_usd if run.cost_usd is not None else run.cap_usd
    return total


def ok_roles(runs):
    return {r for run in runs if run.state == SocialRun.SUCCEEDED
            for r, s in run.stats.items() if s.get('status') == 'ok'}


def gap_roles(runs):
    out = []
    for run in runs:
        if run.state == SocialRun.SUCCEEDED and run.purpose in REGULAR:
            out += [r for r, s in run.stats.items() if s.get('gap') and r not in out]
    return out


def next_run(platform, accounts, now):
    """이번 기간에 시작할 실행 (purpose, 역할 목록, 계정당 글 수). 없으면 None."""
    runs = _period_runs(platform, now)
    if any(r.state in (SocialRun.STARTING, SocialRun.RUNNING) for r in runs):
        return None
    good = ok_roles(runs)
    todo = [a['role'] for a in accounts if a.get(platform) and a['role'] not in good]
    fresh = [r for r in todo if not SocialPost.objects.filter(platform=platform, account=r).exists()]
    if fresh and not any(r.purpose == SocialRun.FIRST for r in runs):  # 처음 보는 계정만 20건(기준선), 기간에 한 번
        return SocialRun.FIRST, fresh, DEEP_LIMIT
    normal = [r for r in runs if r.purpose == SocialRun.NORMAL]
    if todo and len(normal) < MAX_ATTEMPTS[platform] and (
            not normal or now - normal[-1].started_at >= RETRY_GAP[platform]):
        return SocialRun.NORMAL, todo, NORMAL_LIMIT
    gaps = gap_roles(runs)
    if gaps and not any(r.purpose == SocialRun.DEEP for r in runs):
        return SocialRun.DEEP, gaps, DEEP_LIMIT
    return None


def build_input(platform, roles, accounts, limit):
    by_role = {a['role']: a for a in accounts}
    if platform == FACEBOOK:
        return {'startUrls': [{'url': by_role[r]['facebook']} for r in roles], 'resultsLimit': limit,
                'captionText': False}
    return {'username': [by_role[r]['instagram'] for r in roles], 'resultsLimit': limit,
            'dataDetailLevel': 'basicData', 'skipPinnedPosts': True}


# ---- 알림 ----

def alert_once(deps, kind, stamp, text):
    sent = dict(WorkerState.get(ALERTS_KEY) or {})
    if sent.get(kind) == stamp:
        return False
    sent[kind] = stamp
    WorkerState.put(ALERTS_KEY, sent)
    deps.bot.notify_admin(text)
    return True


def _names(accounts, roles):
    names = labels(accounts)
    return '·'.join(names.get(r, r) for r in roles)


def alert_failures(deps, platform, accounts, now):
    """이번 기간 시도를 다 썼는데 정상으로 못 받은 계정이 있으면 한 번 알린다(예산으로 건너뛴 것은 예산 알림이 대신)."""
    runs = _period_runs(platform, now)
    regular = [r for r in runs if r.purpose == SocialRun.NORMAL]
    if (len(regular) < MAX_ATTEMPTS[platform] or any(r.state in (SocialRun.STARTING, SocialRun.RUNNING) for r in runs)
            or all(r.state == SocialRun.SKIPPED for r in regular)):
        return
    good = ok_roles(runs)
    bad = [a['role'] for a in accounts if a.get(platform) and a['role'] not in good]
    if not bad:
        return
    last = regular[-1]
    why = last.error or ', '.join(f'{labels(accounts).get(r, r)} {STATUS_KO.get(s.get("status"), s.get("status"))}'
                                  for r, s in last.stats.items() if s.get('status') != 'ok')
    alert_once(deps, f'fail:{platform}', period_start(platform, now).date().isoformat(),
               f'⚠️ SNS 수집: {PERIOD_KO[platform]} {PLATFORM_KO[platform]}({_names(accounts, bad)}) 수집이 '
               f'{len(regular)}번 모두 실패했어요 — {why}. /mk 로 상태를 볼 수 있어요')


def alert_gaps(deps, platform, accounts, now):
    for run in _period_runs(platform, now):
        still = [r for r, s in run.stats.items() if s.get('gap')] if run.purpose == SocialRun.DEEP else []
        if run.state == SocialRun.SUCCEEDED and still:
            alert_once(deps, f'gap:{platform}', period_start(platform, now).date().isoformat(),
                       f'ℹ️ SNS 수집: {_names(accounts, still)} {PLATFORM_KO[platform]} 글을 {run.limit}건 받아도 '
                       f'지난번 글까지 닿지 못했어요. 사이에 글이 아주 많았거나 고정 글이 섞였을 수 있어요')


# ---- 실행 ----

def fail(run, now, error, cost=None):
    run.state, run.error, run.finished_at = SocialRun.FAILED, error[:300], now
    fields = ['state', 'error', 'finished_at']
    if cost is not None:
        run.cost_usd = cost
        fields.append('cost_usd')
    run.save(update_fields=fields)


def finish_if_done(deps, client, run, data, accounts, now):
    """끝난 실행이면 청구액을 적고 결과를 저장·판정한다. 새 글 목록(끝나지 않았거나 실패면 None)."""
    status = data.get('status', '')
    if status not in FINAL:
        return None
    usage = data.get('usageTotalUsd')
    run.apify_status = status
    run.cost_usd = Decimal(str(usage)).quantize(Decimal('0.001')) if usage is not None else run.cap_usd
    run.save(update_fields=['apify_status', 'cost_usd'])
    if status != 'SUCCEEDED':
        fail(run, now, f'Apify {status}')
        return None
    try:
        items = client.dataset_items(run.dataset_id or data.get('defaultDatasetId', ''))
    except ApifyError as e:
        fail(run, now, f'결과 읽기 실패: {e}')
        return None
    new = store(run, items, accounts, now)
    if new:
        social_judge.judge_pending(deps.llm, now, labels(accounts))
    return new


def start(deps, client, platform, purpose, roles, limit, accounts, now):
    """'했다'를 먼저 적고(SocialRun) Apify를 부른다. 월 예산을 넘으면 부르지 않는다."""
    cap = CAPS[(platform, limit > NORMAL_LIMIT)]
    run = SocialRun.objects.create(platform=platform, purpose=purpose, accounts=list(roles), limit=limit,
                                   cap_usd=cap, started_at=now)
    if month_spent(now) > MONTHLY_BUDGET_USD:
        run.state, run.error, run.finished_at = SocialRun.SKIPPED, '월 예산 초과', now
        run.save(update_fields=['state', 'error', 'finished_at'])
        alert_once(deps, 'budget', kst_now(now).strftime('%Y-%m'),
                   f'⚠️ SNS 수집이 이번 달 예산(${MONTHLY_BUDGET_USD})에 닿아 멈췄어요. 다음 달 1일에 다시 시작해요')
        return run
    try:
        data = client.start_run(ACTORS[platform], build_input(platform, roles, accounts, limit), timeout=RUN_TIMEOUT,
                                max_items=limit * len(roles), max_charge_usd=float(cap), wait=WAIT_SECONDS)
    except ApifyAuthError as e:
        fail(run, now, f'인증 거절: {e}', cost=Decimal('0'))
        alert_once(deps, 'auth', kst_now(now).date().isoformat(),
                   '⚠️ Apify가 토큰을 거절했어요(401/403). Secrets Manager의 APIFY_TOKEN을 확인해 주세요')
        return run
    except ApifyError as e:
        fail(run, now, f'시작 실패: {e}', cost=Decimal('0'))
        return run
    run.apify_run_id, run.dataset_id, run.state = data.get('id', ''), data.get('defaultDatasetId', ''), SocialRun.RUNNING
    run.save(update_fields=['apify_run_id', 'dataset_id', 'state'])
    finish_if_done(deps, client, run, data, accounts, now)
    return run


def poll(deps, client, platform, accounts, now):
    """진행 중인 실행 확인. 15분이 지나도 안 끝나면 중단을 요청하고 실패로 둔다."""
    for run in SocialRun.objects.filter(platform=platform, state__in=(SocialRun.STARTING, SocialRun.RUNNING)):
        if now - run.started_at > GIVE_UP:
            data = {}
            if run.apify_run_id:  # 워커가 오래 멈췄다 돌아온 경우 이미 끝난 실행일 수 있다 → 결과를 버리지 않는다
                try:
                    data = client.get_run(run.apify_run_id)
                except ApifyError:
                    data = {}
                if data.get('status') in FINAL:
                    finish_if_done(deps, client, run, data, accounts, now)
                    continue
                try:
                    client.abort_run(run.apify_run_id)
                except ApifyError:
                    pass
            fail(run, now, '15분 넘게 끝나지 않음')
        elif run.state == SocialRun.RUNNING:
            try:
                data = client.get_run(run.apify_run_id)
            except ApifyError as e:  # 잠깐의 네트워크 오류는 다음 바퀴에 다시 본다
                log.warning('social poll %s: %s', run.apify_run_id, e)
                continue
            finish_if_done(deps, client, run, data, accounts, now)


def run_due(deps, now, client=None):
    """워커가 매 바퀴(약 1분) 부른다. 꺼져 있거나 토큰·계정 설정이 없으면 아무것도 하지 않는다."""
    token, accounts = config()
    if WorkerState.get(SWITCH_KEY) != 'on':
        return
    if not token or not accounts:
        alert_once(deps, 'config', kst_now(now).date().isoformat(),
                   '⚠️ SNS 수집이 켜져 있는데 APIFY_TOKEN 또는 SOCIAL_ACCOUNTS 설정이 없거나 깨졌어요. /mk 로 확인해 주세요')
        return
    client = client or Apify(token)
    local = kst_now(now)
    due = (local.hour, local.minute) >= SOCIAL_AT
    for platform in (FACEBOOK, INSTAGRAM):
        poll(deps, client, platform, accounts, now)
        plan = next_run(platform, accounts, now) if due else None
        if plan:
            start(deps, client, platform, *plan, accounts, now)
        alert_failures(deps, platform, accounts, now)
        alert_gaps(deps, platform, accounts, now)
    if due and WorkerState.get(DAILY_KEY) != local.date().isoformat():
        WorkerState.put(DAILY_KEY, local.date().isoformat())
        daily(deps, accounts, now)


# ---- 매일 점검·보관 ----

def daily(deps, accounts, now):
    """하루 한 번: 오래된 성공 알림 → 책 나중 연결 → 보관 기간 지난 본문 지우기 → 못 한 판정 다시.
    판정(LLM)이 실패해도 앞의 일은 끝나 있게 맨 뒤에 둔다."""
    check_health(deps, accounts, now)
    social_judge.link_later(now)
    prune(now)
    social_judge.judge_pending(deps.llm, now, labels(accounts))


def check_health(deps, accounts, now):
    """마지막 성공이 오래된 계정(페북 3일, 인스타 10일). 실행 실패·빈 결과·차단 등 어떤 경로로 멈추든 여기서 드러난다."""
    ok, since = WorkerState.get(OK_KEY) or {}, WorkerState.get(ON_SINCE_KEY)
    lines = []
    for platform in (FACEBOOK, INSTAGRAM):
        for a in accounts:
            last = ok.get(f'{platform}:{a["role"]}')
            base = last or since
            if a.get(platform) and base and now - datetime.fromisoformat(base) > STALE_AFTER[platform]:
                when = kst_now(datetime.fromisoformat(last)).strftime('%m-%d') if last else '없음'
                lines.append(f'· {a.get("label") or a["role"]} {PLATFORM_KO[platform]}: 마지막 성공 {when}')
    if lines:
        alert_once(deps, 'stale', kst_now(now).date().isoformat(),
                   '⚠️ SNS 수집이 한동안 성공하지 못했어요 — Apify 결과가 비었거나 막혔을 수 있어요\n'
                   + '\n'.join(lines) + '\n/mk 로 최근 실행 이유를 볼 수 있어요')


def prune(now):
    """개인 글 보관: 관련 없는 글 본문 14일, 관련 글 90일, 행 180일."""
    blank = {'text': '', 'shared': {}, 'link': {}, 'text_cleared_at': now}
    SocialPost.objects.filter(text_cleared_at__isnull=True, signal__isnull=True,
                              first_seen__lt=now - KEEP_IRRELEVANT).update(**blank)
    SocialPost.objects.filter(text_cleared_at__isnull=True, signal__isnull=False,
                              first_seen__lt=now - KEEP_RELEVANT).update(**blank)
    SocialPost.objects.filter(first_seen__lt=now - KEEP_ROWS).delete()
    SocialRun.objects.filter(started_at__lt=now - KEEP_ROWS).delete()


# ---- 관리자 ----

def switch(value, now):
    """/mk social on|off. 그 밖에는 상태."""
    if value in ('on', 'off'):
        WorkerState.put(SWITCH_KEY, value)
        if value == 'on':
            WorkerState.put(ON_SINCE_KEY, now.isoformat())
        return f'social={value}'
    return '\n'.join(status_lines(now))


def status_lines(now):
    token, accounts = config()
    lines = [f'social={WorkerState.get(SWITCH_KEY) or "off"}']
    missing = [name for name, v in (('APIFY_TOKEN', token), ('SOCIAL_ACCOUNTS', accounts)) if not v]
    if missing:
        lines.append('social_missing=' + ','.join(missing))
    lines += [f'social_ok[{k}]={v[:16]}' for k, v in sorted((WorkerState.get(OK_KEY) or {}).items())]
    lines.append(f'social_month_usd={month_spent(now)}/{MONTHLY_BUDGET_USD}')
    last = SocialRun.objects.order_by('-started_at', '-id').first()
    if last:
        lines.append(f'social_last_run={last.platform} {last.purpose} {last.state} {last.error}'.strip())
    return lines
