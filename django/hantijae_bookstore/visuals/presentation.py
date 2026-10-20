"""현재 원고의 제작 상태와 같은 방에서 이미 전달한 이미지 위치를 안내한다."""
import logging
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from intake.models import WorkerState
from visuals.assets import sources_current
from visuals.models import CardJob
from visuals.pipeline import _allowed, fingerprint
from visuals.quality import current_sources

log = logging.getLogger('intake')


def draft_status(draft, chat_id):
    """(운영진용 문구, 답장으로 연결할 이미지 번호). 전송/대기열 변경은 하지 않는다."""
    if not (draft.extra or {}).get('cards'):
        return '', None
    try:
        job = CardJob.objects.filter(draft=draft, chat_id=chat_id, fingerprint=fingerprint(draft)).first()
        if job and (not sources_current(job.plan) or not current_sources(job, draft)):
            return '원본 자료가 달라져 이전 이미지를 다시 확인해야 해요.', None
        if not job:
            if _allowed(draft, chat_id, timezone.now()):
                return '이미지 시안은 이 원고에 이어 자동으로 준비해 드립니다.', None
            return '현재 자동 이미지 제작 대상이 아니에요. 구성안만 보관하고 있어요.', None
        images = job.receipt.get('images') or []
        if job.state == 'sent' and images and job.receipt.get('document'):
            text = f'이미지 {len(images)}장과 게시용 원본 ZIP을 이미 전달했어요.'
            text += '\n이 메시지의 답장 대상을 누르면 앞서 보낸 이미지를 볼 수 있어요.'
            text += '\n게시용 원본 ZIP은 그 이미지에 답장으로 보냈어요.'
            target = images[0]
        elif job.state in ('queued', 'building', 'ready'):
            now = timezone.now()
            heartbeat = parse_datetime(str(WorkerState.get('visuals_heartbeat') or ''))
            target = None
            if not _allowed(draft, chat_id, now):
                text = '현재 원고·자료 또는 운영 설정에 따라 이미지 제작·전달이 중단된 상태예요.'
            elif not heartbeat or timezone.is_naive(heartbeat) or now - heartbeat > timedelta(minutes=15):
                text = '이미지 제작이 대기 중이에요. 자동 제작 상태 확인이 필요해요.'
            else:
                text = '이미지 시안을 준비하고 있어요. 밤에는 다음 날 오전에 이어서 전달합니다.'
        elif job.state in ('sending', 'uncertain'):
            text, target = '이미지 전달 결과를 확인하고 있어요. 중복으로 보내지 않을게요.', None
        elif job.state == 'handed_off':
            text, target = '자동 검토를 마치지 못해 개발자에게 자료와 제작 요청을 전달했어요. 아직 완성 시안은 아닙니다.', None
        elif job.state in ('handoff', 'handoff_waiting'):
            text, target = '내용·이미지 검토를 마치지 못해 개발자에게 보낼 제작 자료를 준비하고 있어요.', None
        elif job.state in ('handoff_sending', 'handoff_uncertain'):
            text, target = '개발자에게 제작 자료를 전달한 결과를 확인하고 있어요. 중복 요청하지 않을게요.', None
        elif job.state == 'cancelled':
            text, target = '원고나 자료 상태가 바뀌어 이미지 제작·전달을 중단했어요.', None
        else:
            text, target = '이미지 제작·전달 확인이 필요해요. 아직 완성본으로 안내하지 않습니다.', None
        if job.plan.get('missing'):
            text += '\n원본이 없어 제외: ' + ', '.join(job.plan['missing'])
        if job.plan.get('text_fallbacks'):
            text += '\n원본 대신 글 카드로 구성: ' + ', '.join(job.plan['text_fallbacks'])
        return text, target
    except Exception:
        log.exception('visuals status unavailable')
        return '이미지 제작 상태를 아직 확인하지 못했어요.', None
