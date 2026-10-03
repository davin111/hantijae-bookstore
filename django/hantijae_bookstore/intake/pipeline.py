import logging
import os
import shutil
import time
from datetime import datetime

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from books.models import Category, Series
from context.retention import purge as purge_context
from intake.drafts import create_draft
from intake.drive import download_folder, scan
from intake.extraction import AmbiguousPressRelease, NoPressRelease, run_extraction
from intake.llm import LLMAuthError, LLMError
from intake.models import IntakeSource, WorkerState
from intake.notices import KST
from intake.outage import LAST_OUTAGE, OUTAGE, TG_ALERT_AFTER
from intake.telegram_api import TelegramError
from marketing import tasks as marketing_tasks
from ops import health

log = logging.getLogger('intake')


def _fail(source, deps, message, notify_reviewers=False):
    source.status, source.error = IntakeSource.FAILED, message
    source.save(update_fields=['status', 'error', 'updated_at'])
    deps.bot.notify_admin(f'❌ 자료 #{source.id} {source.title}\n{message}\n다시 시도: /retry {source.id}')
    if notify_reviewers:
        deps.bot.notify_reviewers_or_admin('초안 준비가 늦어지고 있어요. 확인 중이에요.')


MAX_ATTEMPTS = 3


def recover_interrupted(deps, max_attempts=MAX_ATTEMPTS):
    """처리 도중 워커가 죽은(OOM 등) 자료: 재시도하되 max_attempts 넘으면 실패 처리해 무한 재시작을 끊는다."""
    for src in IntakeSource.objects.filter(status=IntakeSource.PROCESSING):
        if src.attempts >= max_attempts:
            src.status = IntakeSource.FAILED
            src.error = f'처리 중 {src.attempts}번 중단됐어요(메모리 부족 등). 자료 크기를 확인해 주세요.'
            src.save(update_fields=['status', 'error', 'updated_at'])
            deps.bot.notify_admin(f'❌ 자료 #{src.id} {src.title}\n{src.error}\n다시 시도: /retry {src.id}')
        else:
            src.status = IntakeSource.QUEUED
            src.save(update_fields=['status', 'updated_at'])


def process_source(source, deps):
    source.status = IntakeSource.PROCESSING
    source.attempts += 1
    source.save(update_fields=['status', 'attempts', 'updated_at'])
    is_drive = source.kind == IntakeSource.DRIVE
    work = os.path.join(settings.INTAKE['WORK_DIR'], 'sources', str(source.id)) if is_drive else source.local_dir
    try:
        if is_drive:
            shutil.rmtree(work, ignore_errors=True)
            download_folder(deps.drive, source.drive_folder_id, work)
        result = run_extraction(work, deps.llm, list(Category.objects.values_list('name', flat=True)),
                                list(Series.objects.values_list('name', flat=True)))
        draft = create_draft(source, result)
    except AmbiguousPressRelease as e:
        _fail(source, deps, '최종 보도자료 후보가 여러 개예요:\n' + '\n'.join(f'• {c}' for c in e.candidates) +
              '\n드라이브에서 하나만 남기거나 이름을 정리한 뒤 다시 시도해 주세요.')
    except NoPressRelease:
        _fail(source, deps, '보도자료 문서(pdf/hwpx/hwp/docx)를 찾지 못했어요.')
    except LLMAuthError as e:
        _fail(source, deps, f'사이드카 인증 실패 — AI_SIDECAR_AUTH_TOKEN 또는 구독 토큰을 확인하세요 ({e})')
    except LLMError as e:
        _fail(source, deps, f'사이드카 호출 실패: {e}', notify_reviewers=True)
    except Exception as e:
        log.exception('process_source failed')
        _fail(source, deps, f'{type(e).__name__}: {e}', notify_reviewers=True)
    else:
        source.status = IntakeSource.PROCESSED
        source.save(update_fields=['status', 'updated_at'])
        deps.bot.notify_draft(draft)
        return draft
    finally:
        if is_drive:
            shutil.rmtree(work, ignore_errors=True)
    return None


def run_pending(deps, limit=1):
    sources = list(IntakeSource.objects.filter(status=IntakeSource.QUEUED).order_by('id')[:limit])
    for src in sources:
        process_source(src, deps)
    return len(sources)


def _scan_due(now):
    last = WorkerState.get('last_drive_scan')
    if not last:
        return True
    return (now - datetime.fromisoformat(last)).total_seconds() >= settings.INTAKE['DRIVE_SCAN_SECONDS']


def _fund_scan_due(now):
    last = WorkerState.get('last_fund_scan')
    if not last:
        return True
    return (now - datetime.fromisoformat(last)).total_seconds() >= settings.INTAKE.get('FUND_SCAN_SECONDS', 6 * 3600)


def _kst_hm(iso):
    return datetime.fromisoformat(iso).astimezone(KST).strftime('%H:%M')


def _notify_admin_safely(deps, text, html=False):
    """텔레그램이 끊긴 동안에는 알림도 실패한다. 그 예외로 워커가 죽지 않게 삼키고 성공 여부만 돌려준다."""
    try:
        deps.bot.notify_admin(text, html=html)
        return True
    except Exception:
        log.exception('admin notice failed')
        return False


def _poll_failed(deps, now, error):
    outage = WorkerState.get(OUTAGE) or {'since': now.isoformat(), 'fails': 0, 'alerted': False}
    outage.update(fails=outage['fails'] + 1, error=str(error)[:300])
    log.warning('telegram poll failed (%d in a row): %s', outage['fails'], error)
    if outage['fails'] >= TG_ALERT_AFTER and not outage['alerted']:
        # 보내기에 실패하면 alerted를 그대로 두어 다음 실패 때 다시 시도한다
        outage['alerted'] = _notify_admin_safely(
            deps, f"⚠️ 텔레그램 수신이 {outage['fails']}번 연속 실패했어요({_kst_hm(outage['since'])}부터). "
                  f"마지막 오류: {outage['error']}")
    WorkerState.put(OUTAGE, outage)


def _poll_recovered(deps, now):
    outage = WorkerState.get(OUTAGE)
    if not outage:
        return
    WorkerState.put(LAST_OUTAGE, {'since': outage['since'], 'until': now.isoformat(), 'fails': outage['fails'],
                                  'error': outage.get('error', '')})
    WorkerState.put(OUTAGE, None)
    if outage['fails'] >= TG_ALERT_AFTER:   # 끊김 알림을 (보내려고) 했으면 회복도 알린다
        _notify_admin_safely(deps, f"✅ 텔레그램 다시 연결됐어요({_kst_hm(outage['since'])}~{_kst_hm(now.isoformat())}, "
                                   f"{outage['fails']}번 실패)")


def _poll_updates(deps, now):
    """getUpdates. 연결 오류(TelegramError: 네트워크·타임아웃·텔레그램 쪽 오류)면 None — 연속 실패를 세어 묶어 알린다."""
    try:
        updates = deps.tg.get_updates(WorkerState.get('telegram_offset', 0) or 0, timeout=50)
    except TelegramError as e:
        _poll_failed(deps, now or timezone.now(), e)
        return None
    _poll_recovered(deps, now or timezone.now())
    return updates


MORNING_AT = (8, 30)   # 조용한 시간(~08:00)이 끝나고, 새벽 마지막 일정(월 07:00 브리핑)에 여유 시간을 더한 뒤


def _morning_check(deps, now):
    """하루 한 번 아침 점검: 살펴볼 것이 있을 때만 관리자 방에 한 메시지. 마케팅 스위치와 상관없이 돈다
    (꺼진 것도 상태의 일부). 실패해도 오늘은 다시 하지 않는다 — 먼저 적고, 바퀴의 나머지는 계속 돈다."""
    local = now.astimezone(KST)
    today = local.date().isoformat()
    if (local.hour, local.minute) < MORNING_AT or WorkerState.get('ops_last_morning') == today:
        return
    WorkerState.put('ops_last_morning', today)
    try:
        text = health.morning_text(health.evaluate(now), settings.SITE_URL)
    except Exception as e:
        log.exception('morning check failed')
        _notify_admin_safely(deps, f'⚠️ 아침 상태 점검 오류: {type(e).__name__}: {e}')
        return
    if text:
        _notify_admin_safely(deps, text, html=True)   # 못 보내도 바퀴의 나머지(마케팅·신간 처리)는 돈다


def run_iteration(deps, now=None, sleep=time.sleep):
    # 장시간 도는 프로세스는 MySQL wait_timeout으로 끊긴 연결을 매 루프 정리해야 한다
    close_old_connections()
    try:
        updates = _poll_updates(deps, now)
        if updates is None:
            sleep(10)
            return
        for update in updates:
            uid = update['update_id']
            if WorkerState.get('telegram_inflight') == uid:
                # 이 업데이트를 처리하다 워커가 죽었다(OOM 등). 같은 입력을 영원히 반복하지 않도록 건너뛴다.
                deps.bot.notify_admin(f'⚠️ 텔레그램 업데이트 {uid} 처리 중 워커가 중단돼 건너뛰었어요')
            else:
                WorkerState.put('telegram_inflight', uid)
                deps.bot.handle_update(update)
            WorkerState.put('telegram_offset', uid + 1)
            WorkerState.put('telegram_inflight', None)
        now = now or timezone.now()
        if deps.drive and WorkerState.get('drive_autoscan', False) and _scan_due(now):
            counts = scan(deps.drive, deps.drive_root, now=now, stable_seconds=settings.INTAKE['DRIVE_STABLE_SECONDS'])
            WorkerState.put('last_drive_scan', now.isoformat())
            for name, folder_id in counts.get('skipped', []):
                # 제목 일치만으로 건너뛰므로 잘못 건너뛴 신간이 조용히 묻히지 않게 알린다
                deps.bot.notify_admin(f'⏭️ 드라이브 폴더 건너뜀: {name}\n사이트에 같은 제목의 책이 있어요. 신간이면 /ingest {folder_id}')
        if WorkerState.get('fund_autoscan', True) and _fund_scan_due(now):
            # 실패해도 다음 확인은 6시간 뒤 — 외부 사이트를 계속 두드리지 않게 먼저 기록한다
            WorkerState.put('last_fund_scan', now.isoformat())
            deps.bot.run_fund_scan(now)
        today = now.astimezone(KST).date().isoformat()
        if WorkerState.get('last_context_purge') != today:
            # 실패해도 오늘은 다시 하지 않는다 — 먼저 적고, 새 책 처리가 밀리지 않게 따로 잡는다
            WorkerState.put('last_context_purge', today)
            try:
                purge_context(now)
            except Exception as e:
                log.exception('context purge failed')
                deps.bot.notify_admin(f'⚠️ 대화 기록 정리 오류: {type(e).__name__}: {e}')
        _morning_check(deps, now)
        marketing_tasks.run_due(deps, now)
        run_pending(deps)
    except Exception as e:
        log.exception('worker iteration failed')
        _notify_admin_safely(deps, f'⚠️ 워커 오류: {type(e).__name__}: {e}')
        sleep(10)
