"""워커 루프(intake.pipeline.run_iteration)가 매 바퀴(약 1분) 부른다. 일정은 KST 기준이다.
작업을 시작하기 전에 '했다'고 먼저 적어서, 도중에 워커가 죽어도 같은 작업을 되풀이하지 않는다."""
import logging
from datetime import datetime

from django.utils import timezone

from intake.models import WorkerState
from marketing import briefing, funding, kit, news, sales
from marketing.models import Briefing
from marketing.timeutil import kst_now, week_start

log = logging.getLogger('intake')
KIT_CHECK_SECONDS = 600
SALES_AT, NEWS_AT, BRIEF_BUILD_AT, BRIEF_SEND_AT, BRIEF_GIVE_UP_AT = (6, 0), (6, 30), (7, 0), (9, 30), (21, 0)


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
    for s in signals or []:
        if s.sensitive and s.book:
            deps.bot.notify_admin(f'🔕 민감한 소식 — 『{s.book.title}』: {s.title}\n'
                                  f'홍보를 쉬려면: /quiet {s.book.title[:12]} YYYY-MM-DD 이유')


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


def _build_kits(deps, m, today):
    """만들 책이 있을 때만 블로그 RSS를 읽는다."""
    if not kit.buildable_books(today):
        return []
    return kit.build_pending(deps.llm, today, m.blog_posts(), notify=deps.bot.notify_admin)


def _run_due(deps, now):
    m = deps.bot.marketing
    if m.mode() == 'off':
        return
    local = kst_now(now)
    today, day, monday = local.date(), local.date().isoformat(), local.weekday() == 0

    if _hm(local) >= SALES_AT and WorkerState.get('marketing_last_sales_scan') != day:
        WorkerState.put('marketing_last_sales_scan', day)
        _sales_block(deps, today, now)
        _guard(deps, 'funding', now, lambda: funding.collect_funding(today, now))

    if monday and _hm(local) >= NEWS_AT and WorkerState.get('marketing_last_news_scan') != day:
        WorkerState.put('marketing_last_news_scan', day)
        _notify_sensitive(deps, _guard(deps, 'news', now, lambda: news.collect_news(today, deps.llm)))

    wk = week_start(today).isoformat()
    if monday and _hm(local) >= BRIEF_BUILD_AT and WorkerState.get('marketing_last_brief_week') != wk:
        WorkerState.put('marketing_last_brief_week', wk)
        _guard(deps, 'brief', now, lambda: briefing.build_weekly(deps.llm, today, now, m.blog_posts()))

    pending = Briefing.objects.filter(week_start=week_start(today), sent_at__isnull=True).first()
    if pending and monday:
        if BRIEF_SEND_AT <= _hm(local) < BRIEF_GIVE_UP_AT:
            _guard(deps, 'brief_send', now, lambda: m.send_briefing(pending, now))
        elif _hm(local) >= BRIEF_GIVE_UP_AT and WorkerState.get('marketing_brief_missed') != wk:
            WorkerState.put('marketing_brief_missed', wk)
            deps.bot.notify_admin('⏭️ 이번 주 브리핑을 보내지 못했어요(항목 없음·모드·시간). /mk 로 확인하세요')

    last = WorkerState.get('marketing_last_kit_check')
    if not last or (now - datetime.fromisoformat(last)).total_seconds() >= KIT_CHECK_SECONDS:
        WorkerState.put('marketing_last_kit_check', now.isoformat())
        _guard(deps, 'kit', now, lambda: _build_kits(deps, m, today))
    _guard(deps, 'kit_send', now, lambda: m.send_pending_kits(now))


def run_due(deps, now=None):
    """R4: 마케팅 훅에서 난 예외가 워커 루프까지 올라가면 그 바퀴 나머지가 통째로 건너뛰고 10초씩 잠들게 된다.
    그래서 run_due 자신도 _guard로 감싸 절대 예외를 내지 않고, 관리자에게 하루 한 번만 알린다."""
    now = now or timezone.now()
    _guard(deps, 'run_due', now, lambda: _run_due(deps, now))
