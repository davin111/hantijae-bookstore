"""워커 루프(intake.pipeline.run_iteration)가 매 바퀴(약 1분) 부른다. 일정은 KST 기준이다.
작업을 시작하기 전에 '했다'고 먼저 적어서, 도중에 워커가 죽어도 같은 작업을 되풀이하지 않는다."""
import logging
import time
from datetime import datetime, timedelta

from django.utils import timezone

from intake.models import WorkerState
from marketing import (bnk, bnk_sales, briefing, funding, grants, instagram, kit, loans, midweek, moments, news,
                       placements, reviews, sales, selections, social)
from marketing.messages import TEXT_LIMIT
from marketing.models import Briefing
from marketing.text import clip
from marketing.timeutil import in_quiet_hours, kst_now, week_start

log = logging.getLogger('intake')
KIT_CHECK_SECONDS = 600
SALES_AT, NEWS_AT, BRIEF_BUILD_AT, BRIEF_SEND_AT, BRIEF_GIVE_UP_AT = (6, 0), (6, 30), (7, 0), (9, 30), (21, 0)
MOMENT_AT, MIDWEEK_BUILD_AT, MIDWEEK_SEND_AT = (5, 0), (5, 30), (9, 30)
ADMIN_QUEUE = 'moment_admin_queue'
BNK_AT = (6, 20)   # 알라딘(06:00)·선정(06:10) 다음, 지원사업(06:40) 전
BNK_MONTH_DAY, BNK_MONTH_AT = 3, (9, 30)   # 전산망이 약 2일 늦어서 1일이 아니라 3일
BNK_FAIL_ALERT_DAYS = 3
GRANT_AT = (6, 40)   # 선정(06:10) 다음, 월요일 브리핑 만들기(07:00) 전. 한 번에 LLM 최대 3번(grants.JUDGE_PER_RUN)
SELECTION_AT = (6, 10)   # 판매 지수(06:00) 다음. LLM을 쓰지 않아 07:00 브리핑 만들기 전에 끝난다
REVIEW_AT = (4, 30)   # 새벽: 검색 200번 남짓과 판별 LLM으로 몇 분 워커를 붙잡는다(그동안 텔레그램 응답이 늦다)
INSTAGRAM_AT = (4, 50)   # 서평 검색(04:30) 뒤, 계기 잡기(05:00) 전. 호출 몇 번뿐(일요일은 협력 계정 12곳 더)
LOAN_AT, LOAN_WEEKDAY = (5, 40), 5   # 토요일 새벽: 정보나루 170권쯤 × 1초
PLACEMENT_AT = (12, 0)   # [올렸어요] 초안이 올라간 곳 찾기. 운영진 개인 계정 수집(06:20~) 뒤. LLM 없음
MISSED_NOTE = '⏭️ 이번 주 브리핑을 보내지 못했어요(항목 없음·모드·시간). /mk 로 확인하세요'


def _hm(local):
    return local.hour, local.minute


def _guard(deps, name, now, fn):
    try:
        return fn()
    except Exception as e:
        log.exception('marketing %s failed', name)
        day = kst_now(now).date().isoformat()
        if WorkerState.get(f'marketing_error_{name}') != day:  # 같은 작업의 오류는 하루 한 번만 알린다
            WorkerState.put(f'marketing_error_{name}', day)
            deps.bot.notify_admin(f'⚠️ 마케팅 {name} 실패: {type(e).__name__}: {e}')
        return None


def _notify_sensitive(deps, signals):
    """민감한 소식은 한 메시지로 모아 알린다(없으면 보내지 않는다)."""
    hits = [s for s in signals or [] if s.sensitive and s.book]
    if not hits:
        return
    lines = [f'🔕 민감한 소식 {len(hits)}건 — 홍보를 쉬려면 아래 /quiet 줄의 날짜·이유를 채워 보내세요']
    lines += [f'· 『{s.book.title}』: {s.title}\n  /quiet {s.book.title[:12]} YYYY-MM-DD 이유' for s in hits]
    deps.bot.notify_admin(clip('\n'.join(lines), TEXT_LIMIT))


def _sales_block(deps, today, now):
    """알라딘 판매 지수 스캔. 사흘 연속 완전히 실패하면(성공 0권) 관리자에게 한 번 알린다(스펙 §6.3)."""
    result = _guard(deps, 'sales', now, lambda: sales.collect_sales(today))
    if result is None:  # collect_sales 자체가 예외를 던진 경우, 이미 _guard가 알렸으니 연속 실패 횟수는 건드리지 않는다
        return
    saved, failed = result
    if saved > 0:
        WorkerState.put('marketing_sales_fail_streak', 0)
    elif failed:
        streak = (WorkerState.get('marketing_sales_fail_streak') or 0) + 1
        WorkerState.put('marketing_sales_fail_streak', streak)
        if streak == 3:
            deps.bot.notify_admin(f'⚠️ 알라딘 판매 지수를 3일째 읽지 못했어요 (실패 {len(failed)}권). '
                                  f'알라딘 페이지 형식이 바뀌었는지 확인해 주세요')


def _build_brief(deps, m, today, now):
    """비었으면 21시까지 기다리지 않고 바로, 버린 까닭과 함께 알린다."""
    b, dropped = briefing.build_weekly(deps.llm, today, now, m.blog_posts())
    if not b.items.exists():
        deps.bot.notify_admin('⏭️ 이번 주 브리핑 후보가 없거나 모두 걸렀어요'
                              + (f'\n버린 항목: {"; ".join(dropped)}' if dropped else ''))
    return b


def _brief_send(deps, m, local, now, wk):
    b = Briefing.objects.filter(week_start=week_start(local.date())).first()
    unsent = b is not None and b.sent_at is None
    if unsent and BRIEF_SEND_AT <= _hm(local) < BRIEF_GIVE_UP_AT:
        _guard(deps, 'brief_send', now, lambda: m.send_briefing(b, now))
    elif _hm(local) >= BRIEF_GIVE_UP_AT and WorkerState.get('marketing_brief_missed') != wk:
        lost = b is None and WorkerState.get('marketing_last_brief_week') == wk  # 만들다가 워커가 멈춘 경우
        has_items = bool(b and b.items.exists())  # 항목 0개인 브리핑은 07:00 알림으로 이미 끝났다
        if unsent or lost:
            WorkerState.put('marketing_brief_missed', wk)
            if lost or has_items:
                deps.bot.notify_admin(MISSED_NOTE)


def _build_kits(deps, m, today):
    """만들 책이 있을 때만 블로그 RSS를 읽는다."""
    if not kit.buildable_books(today):
        return []
    return kit.build_pending(deps.llm, today, m.blog_posts(), notify=deps.bot.notify_admin)


def _later(now, started):
    """바퀴 시작 시각 + 지금까지 걸린 시간. LLM 단계가 몇 분 걸린 뒤 조용한 시간·보내기 시각을 옛 시각으로 판단하지 않게.
    30초 안이면 그대로 둔다(보통 바퀴의 '10분마다' 같은 경계 판단이 흔들리지 않게)."""
    elapsed = time.monotonic() - started
    return now + timedelta(seconds=elapsed) if elapsed >= 30 else now


def _notify_awake(deps, now, text):
    """관리자에게 보낼 요약. 조용한 시간(21~08시)이면 모아 뒀다가 08시 뒤 첫 바퀴에 보낸다(새벽에 휴대폰을 울리지 않게)."""
    if in_quiet_hours(now):
        WorkerState.put(ADMIN_QUEUE, (WorkerState.get(ADMIN_QUEUE) or []) + [text])
    else:
        deps.bot.notify_admin(text)


def _flush_admin_queue(deps, now):
    queued = WorkerState.get(ADMIN_QUEUE) or []
    if queued and not in_quiet_hours(now):
        WorkerState.put(ADMIN_QUEUE, [])
        for text in queued:
            deps.bot.notify_admin(text)


def _moments(deps, now, started):
    """새벽 계기 잡기. 바뀐 게 있으면 관리자 1:1 방에 요약 한 메시지."""
    report = moments.daily(deps, now)
    text = moments.digest(report, now)
    if text:
        _notify_awake(deps, _later(now, started), text)
    return report


def _grant_scan(deps, today, now, started):
    """지원사업 공고 읽기. 알리지 않은 공고 요약은 관리자에게(새벽이면 08시 뒤)."""
    text = grants.digest(grants.scan(deps.llm, today))
    if text:
        _notify_awake(deps, _later(now, started), text)


def _bnk_login_rejected(deps, today, now, started, error):
    """계정 거부: 다시 시도하면 대표 계정이 잠길 수 있어 자동 로그인을 멈추고 관리자에게 알린다(/bnk on으로 다시 시작)."""
    bnk_sales.block(today)
    _notify_awake(deps, _later(now, started), f'{bnk_sales.LOGIN_FAIL}\n사이트 안내: {error}')


def _bnk_collect(deps, today, now, started):
    """전산망 판매 수집. 계정 거부는 자동 로그인을 멈추고 알린다. 그 밖의 오류는 _guard가 하루 한 번 알리고,
    사흘 연속이면 화면이 바뀌었을 수 있다고 한 번 더 알린다."""
    try:
        with bnk.client_from_settings() as client:
            bnk_sales.collect(client, today)
    except bnk.BnkLoginError as e:
        _bnk_login_rejected(deps, today, now, started, e)
        return
    except Exception:
        streak = (WorkerState.get('bnk_fail_streak') or 0) + 1
        WorkerState.put('bnk_fail_streak', streak)
        if streak == BNK_FAIL_ALERT_DAYS:
            _notify_awake(deps, _later(now, started),
                          f'⚠️ 전산망 판매를 {streak}일째 읽지 못했어요 — 화면이 바뀌었는지 확인해 주세요')
        raise
    WorkerState.put('bnk_fail_streak', 0)


def _bnk_month(deps, today, now, started):
    try:
        with bnk.client_from_settings() as client:
            text = bnk_sales.monthly_text(client, bnk_sales.last_month_start(today), html=True)
    except bnk.BnkLoginError as e:
        _bnk_login_rejected(deps, today, now, started, e)
        return
    if text:
        deps.bot.notify_admin(text, html=True)


def _build_midweek(deps, m, today, now, started):
    made, dropped = midweek.build(deps.llm, today, now, m.mode())
    if dropped:
        _notify_awake(deps, _later(now, started), '⏭️ 주중 제안에서 버린 항목: ' + '; '.join(dropped))
    return made


def _midweek_blocks(deps, m, local, now, today, day, started):
    """화~토 05:30 만들기, 09:30~21:00 보내기. 워커가 늦게 켜져도 같은 바퀴에서 만들고 바로 보낸다.
    못 보낸 지난 주중 제안은 모드와 상관없이 풀어 준다(보내기를 꺼도 그 계기가 브리핑에서 빠지지 않게)."""
    _guard(deps, 'midweek', now, lambda: midweek.release_stale(today))
    if local.weekday() not in midweek.BUILD_DAYS or WorkerState.get('midweek_mode', 'off') == 'off':
        return
    if _hm(local) >= MIDWEEK_BUILD_AT and WorkerState.get('midweek_last_build') != day:
        WorkerState.put('midweek_last_build', day)
        _guard(deps, 'midweek', now, lambda: _build_midweek(deps, m, today, now, started))
    send_now = _later(now, started)
    if kst_now(send_now).date() == today and MIDWEEK_SEND_AT <= _hm(kst_now(send_now)) < BRIEF_GIVE_UP_AT:
        _guard(deps, 'midweek_send', send_now, lambda: m.send_midweek(send_now))


def _run_due(deps, now):
    m = deps.bot.marketing
    if m.mode() == 'off':
        return
    started = time.monotonic()
    local = kst_now(now)
    today, day, monday = local.date(), local.date().isoformat(), local.weekday() == 0
    _flush_admin_queue(deps, now)

    # 계기 잡기는 LLM으로 몇 분 걸려 워커가 텔레그램을 못 본다 → 새벽에, 월요일 07:00 브리핑 만들기보다 먼저
    if (_hm(local) >= MOMENT_AT and WorkerState.get('moment_mode', 'off') != 'off'
            and WorkerState.get('moment_last_run') != day):
        WorkerState.put('moment_last_run', day)
        _guard(deps, 'moment', now, lambda: _moments(deps, now, started))
    _midweek_blocks(deps, m, local, now, today, day, started)
    now = _later(now, started)  # 뒤 블록(판매 지수·브리핑·묶음)은 지금 시각으로 판단한다
    local = kst_now(now)
    today, day, monday = local.date(), local.date().isoformat(), local.weekday() == 0

    if _hm(local) >= REVIEW_AT and WorkerState.get('marketing_last_review_scan') != day:
        WorkerState.put('marketing_last_review_scan', day)
        _guard(deps, 'review', now, lambda: reviews.run(deps, today, notify=lambda text: _notify_awake(deps, now, text)))

    if _hm(local) >= INSTAGRAM_AT and WorkerState.get('marketing_last_instagram_scan') != day:
        WorkerState.put('marketing_last_instagram_scan', day)
        _guard(deps, 'instagram', now,
               lambda: instagram.run(deps, today, notify=lambda text: _notify_awake(deps, now, text)))

    if (local.weekday() == LOAN_WEEKDAY and _hm(local) >= LOAN_AT
            and WorkerState.get('marketing_last_loan_scan') != day):
        WorkerState.put('marketing_last_loan_scan', day)
        _guard(deps, 'loan', now, lambda: loans.collect(today))

    if _hm(local) >= SALES_AT and WorkerState.get('marketing_last_sales_scan') != day:
        WorkerState.put('marketing_last_sales_scan', day)
        _sales_block(deps, today, now)
        _guard(deps, 'funding', now, lambda: funding.collect_funding(today, now))

    if _hm(local) >= SELECTION_AT and WorkerState.get('marketing_last_selection_scan') != day:
        WorkerState.put('marketing_last_selection_scan', day)
        _guard(deps, 'selection', now, lambda: selections.run_scan(deps, today, now))

    bnk_on = bnk_sales.mode() == 'on' and not bnk_sales.blocked()   # 계정 거부 뒤에는 /bnk on 전까지 로그인하지 않는다
    if bnk_on and _hm(local) >= BNK_AT and WorkerState.get('bnk_last_run') != day:
        WorkerState.put('bnk_last_run', day)
        _guard(deps, 'bnk', now, lambda: _bnk_collect(deps, today, now, started))
    month_start = bnk_sales.last_month_start(today)
    month = month_start.strftime('%Y-%m')
    # 그 달을 다 읽었을 때만(로그인 전에 DB로 확인) 보내고, 그때 적는다 — 덜 읽은 달은 다음 날 다시 본다
    if (bnk_on and local.day >= BNK_MONTH_DAY and _hm(local) >= BNK_MONTH_AT and not in_quiet_hours(now)
            and WorkerState.get('bnk_last_monthly') != month and bnk_sales.month_ready(month_start)):
        WorkerState.put('bnk_last_monthly', month)
        _guard(deps, 'bnk_month', now, lambda: _bnk_month(deps, today, now, started))

    if (_hm(local) >= GRANT_AT and grants.mode() != 'off'
            and WorkerState.get('grant_last_scan') != day):
        WorkerState.put('grant_last_scan', day)
        _guard(deps, 'grant', now, lambda: _grant_scan(deps, today, now, started))

    # 운영진 개인 SNS: 06:20 뒤 시작, 진행 중인 실행 확인은 매 바퀴(시각·꺼짐은 social이 판단)
    _guard(deps, 'social', now, lambda: social.run_due(deps, now))

    if _hm(local) >= PLACEMENT_AT and WorkerState.get('marketing_last_placement_scan') != day:
        WorkerState.put('marketing_last_placement_scan', day)
        _guard(deps, 'placement', now, lambda: placements.update_recent(
            now, blog_posts=m.blog_posts, labels=social.labels(social.config()[1])))

    if monday and _hm(local) >= NEWS_AT and WorkerState.get('marketing_last_news_scan') != day:
        WorkerState.put('marketing_last_news_scan', day)
        _notify_sensitive(deps, _guard(deps, 'news', now, lambda: news.collect_news(today, deps.llm)))

    wk = week_start(today).isoformat()
    if monday and _hm(local) >= BRIEF_BUILD_AT and WorkerState.get('marketing_last_brief_week') != wk:
        WorkerState.put('marketing_last_brief_week', wk)
        _guard(deps, 'brief', now, lambda: _build_brief(deps, m, today, now))
    if monday:
        _brief_send(deps, m, local, now, wk)

    last = WorkerState.get('marketing_last_kit_check')
    if not last or (now - datetime.fromisoformat(last)).total_seconds() >= KIT_CHECK_SECONDS:
        WorkerState.put('marketing_last_kit_check', now.isoformat())
        _guard(deps, 'kit', now, lambda: _build_kits(deps, m, today))
    _guard(deps, 'kit_send', now, lambda: m.send_pending_kits(now))
    _guard(deps, 'grant_send', now, lambda: m.send_grants(_later(now, started)))


def run_due(deps, now=None):
    """R4: 마케팅 훅에서 난 예외가 워커 루프까지 올라가면 그 바퀴 나머지가 통째로 건너뛰고 10초씩 잠들게 된다.
    그래서 run_due 자신도 _guard로 감싸 절대 예외를 내지 않고, 관리자에게 하루 한 번만 알린다."""
    now = now or timezone.now()
    _guard(deps, 'run_due', now, lambda: _run_due(deps, now))
