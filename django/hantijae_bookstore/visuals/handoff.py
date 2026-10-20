"""미완성 시안은 검수방 대신 등록된 관리자 1:1로 한 번만 제작 요청한다."""
import hashlib
import html
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from django.utils import timezone

from books.models import Book
from intake.models import TelegramChat
from marketing.models import Signal
from marketing.timeutil import in_quiet_hours
from visuals.assets import MAX_BYTES, root, source_path
from visuals.models import ApprovedImage, CardJob
from visuals.quality import source_bundle

REQUEST = '''첨부한 한티재 카드 제작 자료를 바탕으로 카드 3~4장을 완성해 주세요.
1. 출처 원문을 대조해 구체적인 장면·관점을 고르세요. 출처가 없으면 창작하지 말고 필요한 자료를 알려 주세요.
2. 내용이 장마다 전진하도록 편집하고, 단독 사용과 순서 변경이 가능하게 만드세요.
3. 표지는 원본을 보존하고 한글 조판·위계·구도를 다듬으세요. 카드 안에 순번/총장수는 넣지 마세요.
4. 원문·인용 검토와 실제 이미지/모바일 가독성 검토를 별도로 수행하고 부족하면 수정하세요.
5. 최종 1080×1350 PNG와 원본 ZIP, 게시글, 출처와 검토 결과를 제공해 주세요. SNS에는 자동 게시하지 마세요.
자동 시안과 기존 게시글은 미승인 참고 자료입니다. 검토 실패 사유를 먼저 읽어 주세요.'''


def package(job):
    folder = root() / str(job.pk)
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / 'production-request.zip'
    proposal, q = job.draft.proposal, job.plan.get('quality', {})
    ids = set(proposal.extra.get('book_ids', []))
    if proposal.book_id:
        ids.add(proposal.book_id)
    books = list(Book.objects.filter(pk__in=ids).order_by('pk'))
    sources = []
    for book in books:
        for source in source_bundle(SimpleNamespace(proposal=SimpleNamespace(book=book))):
            sources.append({**source, 'label': f'『{book.title}』 — ' + source['label']})
    signal_ids = ([proposal.signal_id] if proposal.signal_id else []) + proposal.extra.get('signals', []) + proposal.extra.get('more_signal_ids', [])
    for signal in Signal.objects.filter(pk__in=signal_ids, sensitive=False, relevant=True):
        detail = signal.detail or {}
        fields = ('type', 'status', 'date', 'time', 'starts_at', 'ends_at', 'location', 'place', 'venue', 'address', 'event', 'summary', 'description', 'url')
        facts = {k: detail[k] for k in fields if k in detail}
        sources.append({'label': '행사·소식 원문 확인 필요: ' + signal.title, 'url': signal.url,
                        'text': '기록된 날짜: ' + str(signal.happens_on or '미확인') + '\n' + json.dumps(facts, ensure_ascii=False)})
    missing, remaining = [], 25_000_000
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('제작 요청.md', '# 제작 요청\n\n' + REQUEST + '\n\n## 자동 제작 보류 이유\n' + job.error)
        z.writestr('게시글 초안.txt', job.draft.title + '\n\n' + job.draft.body)
        z.writestr('출처.md', '\n\n'.join('## '+s['label']+'\n'+s['url']+'\n\n'+s['text'] for s in sources)
                   or '자동으로 확보한 원문이 없습니다. 책/행사 원자료 확인이 필요합니다.')
        cards = q.get('cards') or job.plan.get('cards') or job.draft.extra.get('cards', [])
        z.writestr('카드 문구.json', json.dumps(cards, ensure_ascii=False, indent=2))
        z.writestr('검토 기록.json', json.dumps(q.get('attempts', []), ensure_ascii=False, indent=2))
        sections = []
        for i, card in enumerate(cards, 1):
            text = '\n\n'.join(str(card.get(k, '')) for k in ('heading', 'body', 'credit', 'text', 'show') if card.get(k))
            sections.append('<section contenteditable="true"><p>' + html.escape(text).replace('\n', '<br>') + '</p></section>')
        z.writestr('문구 편집.html', '<!doctype html><html lang="ko"><meta charset="utf-8"><title>미승인 카드 문구 편집</title>'
                   '<style>body{background:#eee;font:20px/1.7 sans-serif;margin:40px}section{background:#fff;padding:40px;margin:24px 0;max-width:700px}h1{font-size:24px}</style>'
                   '<h1>미승인 시안 · 문구를 클릭해 고칠 수 있습니다. 수정한 글은 복사해 사용하세요.</h1>' + ''.join(sections) + '</html>')
        # 확보 실패한 파일 하나가 요청 전체를 막지 않는다. 원본 위치를 남겨 이어서 찾게 한다.
        for book in books:
            if book.cover_image:
                try:
                    with book.cover_image.open('rb') as f:
                        data = f.read(min(MAX_BYTES, remaining)+1)
                    if len(data) > min(MAX_BYTES, remaining):
                        raise ValueError('크기 제한')
                    suffix = Path(book.cover_image.name).suffix.lower()
                    z.writestr('원본/' + str(book.pk) + '-표지' + (suffix if suffix in ('.jpg','.jpeg','.png','.webp') else '.img'), data)
                    remaining -= len(data)
                except Exception:
                    missing.append('표지 파일 수신 실패. 공식 책 페이지에서 원본 확인: '+f'https://hantijae-bookstore.com/book={book.pk}')
            for asset in ApprovedImage.objects.filter(book=book, active=True).order_by('-id')[:8]:
                try:
                    with source_path(asset).open('rb') as f:
                        data = f.read(min(MAX_BYTES, remaining) + 1)
                    if len(data) > min(MAX_BYTES, remaining):
                        raise ValueError('크기 제한')
                    z.writestr('원본/' + str(asset.pk) + Path(asset.path).suffix, data)
                    remaining -= len(data)
                    missing.append('포함 원본 출처: ' + asset.label + ' — ' + asset.source)
                except Exception:
                    missing.append('원본 수신 실패: ' + asset.label + ' — ' + asset.source)
        for name in job.files:
            if Path(name).name == name and name.endswith('.png'):
                try:
                    with (folder/name).open('rb') as f:
                        data = f.read(remaining + 1)
                    if len(data) > remaining:
                        missing.append('크기 제한으로 시안 제외: ' + name)
                    else:
                        z.writestr('미승인 시안/'+name, data)
                        remaining -= len(data)
                except OSError:
                    missing.append('시안 파일 없음: ' + name)
        z.writestr('원본 자료 안내.txt', '\n'.join(missing))
    return archive


def deliver_handoff(job, tg, can_send):
    job.refresh_from_db()
    if job.state != 'handoff' or in_quiet_hours(timezone.now()):
        return
    admins = list(TelegramChat.objects.filter(kind=TelegramChat.ADMIN, chat_id__gt=0)[:2])
    if len(admins) != 1:
        job.state = 'handoff_waiting'
        job.error = '개인 제작 요청 수신처 확인 필요: 관리자 1:1이 하나로 정해져 있지 않음'
        job.save(update_fields=['state', 'error', 'updated_at'])
        return
    try:
        payload = package(job).read_bytes()
    except Exception:
        # 디스크/개별 자료 오류도 다음 작업을 막지 않는다. 최소 자료는 메모리에서 묶는다.
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('제작 요청.md', REQUEST + '\n\n파일을 묶는 중 오류가 있어 요청문과 게시글만 담았습니다.\n' + job.error)
            z.writestr('게시글 초안.txt', job.draft.title + '\n\n' + job.draft.body)
            if job.draft.proposal.book_id:
                z.writestr('출처 링크.txt', f'https://hantijae-bookstore.com/book={job.draft.proposal.book_id}')
        payload = buffer.getvalue()
    if not can_send():
        CardJob.objects.filter(pk=job.pk).update(state='cancelled')
        return
    # 자료를 모으는 사이 바뀐 수신처나 야간 상태를 실제 전송 직전에 다시 본다.
    current_admins = list(TelegramChat.objects.filter(kind=TelegramChat.ADMIN, chat_id__gt=0).values_list('chat_id', flat=True)[:2])
    if current_admins != [admins[0].chat_id] or in_quiet_hours(timezone.now()):
        return
    digest = hashlib.sha256(payload).hexdigest()
    if not CardJob.objects.filter(pk=job.pk, state='handoff').update(state='handoff_sending', started_at=timezone.now()):
        return
    title = job.draft.proposal.book.title if job.draft.proposal.book else job.draft.title
    caption = (f'『{title}』 카드 제작을 부탁드립니다.\n\n자동 검토를 마치지 못해 검수방에는 보내지 않았습니다.\n'
               + job.error[:180] + '\n\nZIP을 Codex 등에 첨부한 뒤 다음 문장을 붙여 넣으세요.\n\n'
               '“첨부한 제작 요청.md를 따라 카드를 완성해 줘. 출처 대조와 내용·디자인 검토를 거쳐 PNG와 ZIP으로 제공해 줘.”'
               '\n\n문구·출처·확보한 원본·미승인 시안과 검토 기록을 묶었습니다. 없는 자료는 안내 파일에 적었습니다.')
    try:
        result = tg.call('sendDocument', chat_id=admins[0].chat_id, caption=caption[:1000],
                         _files={'document': ('hantijae-production-request.zip', payload, 'application/zip')}, _http_timeout=90)
        job.receipt['handoff'] = {'chat_id': admins[0].chat_id, 'message_id': result['message_id'], 'zip_sha256': digest}
        job.state, job.completed_at = 'handed_off', timezone.now()
        job.save(update_fields=['receipt', 'state', 'completed_at', 'updated_at'])
    except Exception:
        CardJob.objects.filter(pk=job.pk).update(state='handoff_uncertain', error='개인 제작 요청 전송 결과 확인 필요. 자동 재전송하지 않음')
