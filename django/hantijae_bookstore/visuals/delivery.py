"""부분 전송 영수증을 즉시 보존한다. 결과 불명인 전송은 재시도하지 않는다."""
import hashlib
import zipfile
from pathlib import Path

from django.utils import timezone

from marketing.models import DraftMessage
from marketing.timeutil import in_quiet_hours
from visuals.assets import root
from visuals.models import CardJob


def deliver(job, tg, can_send):
    job.refresh_from_db()
    if job.state != 'ready':
        return
    from visuals.quality import files_approved, hold
    if not files_approved(job):
        if job.receipt.get('images'):
            CardJob.objects.filter(pk=job.pk).update(state='uncertain', error='전송된 카드의 검토 기록 확인 필요')
        else:
            hold(job, '실제로 검토한 이미지 파일과 일치하지 않아 확인이 필요합니다')
        return
    if in_quiet_hours(timezone.now()):
        return
    folder = root() / str(job.pk)
    paths = []
    for name in job.files:
        if Path(name).name != name or not name.endswith('.png'):
            raise ValueError('이미지 파일 경로 오류')
        paths.append(folder / name)
    if not 1 <= len(paths) <= 4:
        raise ValueError('보낼 이미지 없음')
    archive = folder / 'originals.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in paths:
            z.write(path, path.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    caption = f'『{job.draft.proposal.book.title}』 게시물 이미지 시안' if job.draft.proposal.book else '게시물 이미지 시안'
    caption += f'\n{len(paths)}장 · 1080×1350\n원문 대조와 별도 AI 내용·이미지 검토를 거친 시안입니다. 최종 확인 후 사용해 주세요. 게시용 원본은 ZIP으로 함께 드립니다.'
    if job.plan.get('illustration'):
        caption += '\nAI가 만든 도형 일러스트가 포함되어 있습니다.'
    missing = job.plan.get('missing', [])
    if missing:
        caption += '\n원본 자료가 없어 제외: ' + ', '.join(missing)
    if job.plan.get('text_fallbacks'):
        caption += '\n원본 자료가 없어 글 카드로 구성: ' + ', '.join(job.plan['text_fallbacks'])
    caption = caption[:950]
    reply = {'message_id': job.reply_to, 'allow_sending_without_reply': True}
    if not can_send():
        CardJob.objects.filter(pk=job.pk).update(state='cancelled')
        return
    if not CardJob.objects.filter(pk=job.pk, state='ready').update(state='sending', started_at=timezone.now()):
        return
    ids = job.receipt.get('images', [])
    if not ids:
        if len(paths) == 1:
            result = tg.call('sendPhoto', chat_id=job.chat_id, reply_parameters=reply, caption=caption,
                             _files={'photo': ('01.png', paths[0].read_bytes(), 'image/png')}, _http_timeout=90)
            results = [result]
        else:
            media, files = [], {}
            for i, path in enumerate(paths):
                key = f'photo{i}'
                media.append({'type': 'photo', 'media': f'attach://{key}', **({'caption': caption} if i == 0 else {})})
                files[key] = (path.name, path.read_bytes(), 'image/png')
            results = tg.call('sendMediaGroup', chat_id=job.chat_id, reply_parameters=reply,
                              media=media, _files=files, _http_timeout=90)
        ids = [r['message_id'] for r in results]
        job.receipt = {'images': ids, 'zip_sha256': digest}
        job.save(update_fields=['receipt', 'updated_at'])
        for mid in ids:
            DraftMessage.objects.get_or_create(draft=job.draft, chat_id=job.chat_id, message_id=mid)
    if not can_send():
        CardJob.objects.filter(pk=job.pk).update(state='cancelled', error='앨범 전송 후 원고 상태 변경; ZIP 중단')
        return
    if in_quiet_hours(timezone.now()):
        CardJob.objects.filter(pk=job.pk).update(state='ready')
        return
    result = tg.call('sendDocument', chat_id=job.chat_id,
                     reply_parameters={'message_id': ids[0], 'allow_sending_without_reply': True},
                     caption='게시용 PNG 원본입니다. 사진 앨범은 텔레그램에서 압축될 수 있으니 이 파일을 사용해 주세요.',
                     _files={'document': ('hantijae-cards.zip', archive.read_bytes(), 'application/zip')}, _http_timeout=90)
    job.receipt['document'] = result['message_id']
    job.state, job.completed_at = 'sent', timezone.now()
    job.save(update_fields=['receipt', 'state', 'completed_at', 'updated_at'])
    DraftMessage.objects.get_or_create(draft=job.draft, chat_id=job.chat_id, message_id=result['message_id'])
