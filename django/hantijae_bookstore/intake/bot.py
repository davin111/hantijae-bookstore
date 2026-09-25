"""텔레그램 업데이트 처리. 권한은 대화방 단위: 등록된 가족 그룹과 관리자 1:1 방만 응답한다."""
import logging
import os
import re
import unicodedata
from typing import Protocol

from django.conf import settings

from books.preview import preview_url
from intake import drafts, messages
from intake.llm import LLMError
from intake.models import BookDraft, IntakeSource, PendingPatch, TelegramChat, WorkerState
from intake.notion import fill_notion_row
from intake.publish import PublishBlocked, publish

log = logging.getLogger('intake')
FOLDER_RE = re.compile(r'drive\.google\.com/(?:drive/(?:u/\d+/)?folders/|open\?id=)([\w-]{10,})')
ADMIN_COMMANDS = ('/status', '/mode', '/drive', '/notion', '/baseline', '/ingest', '/retry')
DONE_WORDS = ('완료', '끝', '다 보냈어요', '다보냈어요')
MAX_TG_FILE = 20 * 1024 * 1024


def parse_folder_id(text):
    m = FOLDER_RE.search(text or '')
    return m.group(1) if m else None


def split_command(text):
    if not text.startswith('/'):
        return '', text
    head, _, arg = text.partition(' ')
    return head.split('@')[0].lower(), arg.strip()


class DriveOps(Protocol):
    def baseline(self) -> int: ...
    def ingest(self, folder_id: str) -> IntakeSource: ...


class Bot:
    def __init__(self, tg, llm, notion=None, drive_ops=None, config=None):
        self.tg, self.llm, self.notion, self.drive_ops = tg, llm, notion, drive_ops
        self.config = config or settings.INTAKE

    # ---- 방 ----
    def chat_kind(self, chat_id):
        return TelegramChat.objects.filter(chat_id=chat_id).values_list('kind', flat=True).first()

    def _chat(self, kind):
        return TelegramChat.objects.filter(kind=kind).order_by('-id').values_list('chat_id', flat=True).first()

    def review_chat_id(self):
        family = self._chat(TelegramChat.FAMILY)
        return family if WorkerState.get('mode', 'admin_only') == 'live' and family else self._chat(TelegramChat.ADMIN)

    def notify_admin(self, text):
        admin = self._chat(TelegramChat.ADMIN)
        if admin:
            self.tg.send_message(admin, text)

    def notify_family_or_admin(self, text):
        chat = self.review_chat_id()
        if chat:
            self.tg.send_message(chat, text)

    # ---- 초안 메시지 ----
    def _caption(self, draft):
        return messages.draft_caption(drafts.book_snapshot(draft.book), draft.warnings, preview_url(draft.book.id),
                                      published=draft.state == BookDraft.PUBLISHED)

    def _buttons(self, draft):
        return messages.draft_buttons(draft.id, draft.version, published=draft.state == BookDraft.PUBLISHED)

    def notify_draft(self, draft):
        chat = self.review_chat_id()
        if not chat:
            return
        if draft.book.cover_image:
            with draft.book.cover_image.open('rb') as fh:
                sent = self.tg.send_photo(chat, fh.read(), self._caption(draft), self._buttons(draft))
            kind = 'photo'
        else:
            sent = self.tg.send_message(chat, self._caption(draft), buttons=self._buttons(draft))
            kind = 'text'
        draft.chat_id, draft.message_id = chat, sent['message_id']
        # 텔레그램은 텍스트 메시지에 editMessageCaption 을 거절한다 → 나중에 고칠 때 종류별 API를 쓴다
        draft.files = dict(draft.files or {}, message_kind=kind)
        draft.save(update_fields=['chat_id', 'message_id', 'files', 'updated_at'])
        admin_notes = [w['message'] for w in draft.warnings if w['audience'] == 'admin']
        if admin_notes:
            self.notify_admin(f'초안 #{draft.id} 관리자 메모\n' + '\n'.join(f'• {n}' for n in admin_notes))

    def _edit(self, draft, text, buttons=None):
        if (draft.files or {}).get('message_kind') == 'text':
            self.tg.edit_text(draft.chat_id, draft.message_id, text, buttons)
        else:
            self.tg.edit_caption(draft.chat_id, draft.message_id, text, buttons)

    def refresh_draft_message(self, draft):
        if draft.message_id:
            self._edit(draft, self._caption(draft), self._buttons(draft))

    # ---- 진입점 ----
    def handle_update(self, update):
        try:
            if 'callback_query' in update:
                self.on_callback(update['callback_query'])
            elif 'message' in update:
                self.on_message(update['message'])
        except Exception as e:  # 한 업데이트의 실패가 워커를 멈추지 않게
            log.exception('update failed')
            self.notify_admin(f'⚠️ 업데이트 처리 오류: {type(e).__name__}: {e}')

    def on_message(self, msg):
        chat = msg['chat']
        chat_id = chat['id']
        text = (msg.get('text') or msg.get('caption') or '').strip()
        actor = msg.get('from', {}).get('first_name', '')
        cmd, arg = split_command(text)
        if cmd == '/start' and chat.get('type') == 'private':
            return self.register(chat, TelegramChat.ADMIN, arg)
        if cmd == '/register' and chat.get('type') in ('group', 'supergroup'):
            return self.register(chat, TelegramChat.FAMILY, arg)
        kind = self.chat_kind(chat_id)
        if not kind:
            return
        if kind == TelegramChat.ADMIN and cmd in ADMIN_COMMANDS:
            return self.admin_command(chat_id, cmd, arg)
        if cmd == '/newbook':
            return self.start_newbook(chat_id, msg['message_id'], actor)
        reply = msg.get('reply_to_message')
        if reply:
            src = IntakeSource.objects.filter(path=f"tg:{chat_id}:{reply['message_id']}", status=IntakeSource.SEEN).first()
            if src:
                return self.collect_newbook(src, msg, text)
            draft = BookDraft.objects.filter(chat_id=chat_id, message_id=reply['message_id']).select_related('book').first()
            if draft is None:
                patch = PendingPatch.objects.filter(message_id=reply['message_id'], draft__chat_id=chat_id) \
                    .select_related('draft__book').first()
                draft = patch.draft if patch else None      # "이렇게 바꿀게요"에 단 답장도 같은 초안의 수정 요청
            if draft and draft.book and draft.state in (BookDraft.REVIEW, BookDraft.PUBLISHED):
                return self.on_draft_reply(draft, msg, text, actor)
        if kind == TelegramChat.ADMIN and parse_folder_id(text):
            return self.ingest_folder(chat_id, parse_folder_id(text))
        if reply and kind == TelegramChat.FAMILY:
            # privacy mode 에선 봇 메시지에 단 답장만 들어온다 → 초안이 아닌 메시지에 답장한 경우 안내
            return self.tg.send_message(chat_id, '고칠 내용은 책 초안 사진 메시지(📕)에 답장으로 적어 주세요.',
                                        reply_to=msg['message_id'])

    def register(self, chat, kind, code):
        expected = self.config.get('TELEGRAM_INVITE_CODE')
        if not expected or code != expected:
            return
        TelegramChat.objects.update_or_create(chat_id=chat['id'], defaults={'kind': kind, 'title': chat.get('title', '')})
        self.tg.send_message(chat['id'], '등록됐어요. 새 책 초안이 준비되면 여기로 알려 드릴게요.' if kind == TelegramChat.FAMILY
                             else '관리자 방으로 등록됐어요. /status 로 상태를 볼 수 있어요.')

    def admin_command(self, chat_id, cmd, arg):
        if cmd == '/status':
            queued = IntakeSource.objects.filter(status=IntakeSource.QUEUED).count()
            review = BookDraft.objects.filter(state=BookDraft.REVIEW).count()
            text = (f"mode={WorkerState.get('mode', 'admin_only')} drive={WorkerState.get('drive_autoscan', False)} "
                    f"notion={WorkerState.get('notion_write', False)}\n대기 {queued}건 · 검수 중 {review}건 · "
                    f"마지막 드라이브 확인 {WorkerState.get('last_drive_scan', '-')}")
        elif cmd == '/mode' and arg in ('live', 'admin_only'):
            WorkerState.put('mode', arg)
            text = f'mode={arg}'
        elif cmd in ('/drive', '/notion') and arg in ('on', 'off'):
            if cmd == '/drive' and arg == 'on' and not WorkerState.get('drive_baseline_at'):
                text = '먼저 /baseline 으로 기존 폴더를 기준선에 등록해 주세요'
            else:
                WorkerState.put('drive_autoscan' if cmd == '/drive' else 'notion_write', arg == 'on')
                text = f'{cmd[1:]}={arg}'
        elif cmd == '/baseline' and self.drive_ops:
            text = f'기존 폴더 {self.drive_ops.baseline()}개를 기준선으로 등록했어요'
        elif cmd == '/ingest' and parse_folder_id(arg) or (cmd == '/ingest' and re.fullmatch(r'[\w-]{10,}', arg)):
            return self.ingest_folder(chat_id, parse_folder_id(arg) or arg)
        elif cmd == '/retry' and arg.isdigit():
            n = IntakeSource.objects.filter(pk=int(arg)).update(status=IntakeSource.QUEUED, error='', attempts=0)
            text = '다시 대기열에 넣었어요' if n else '그런 자료가 없어요'
        else:
            text = '사용법: /status · /mode live|admin_only · /drive on|off · /notion on|off · /baseline · /ingest <폴더 링크> · /retry <번호>'
        self.tg.send_message(chat_id, text)

    def ingest_folder(self, chat_id, folder_id):
        if not self.drive_ops:
            return self.tg.send_message(chat_id, '드라이브 연결이 설정되지 않았어요')
        src = self.drive_ops.ingest(folder_id)
        self.tg.send_message(chat_id, f"'{src.title}' 폴더를 처리 대기열에 넣었어요. 초안이 준비되면 알려 드릴게요.")

    def start_newbook(self, chat_id, message_id, actor):
        work = os.path.join(self.config['WORK_DIR'], 'telegram', f'{chat_id}-{message_id}')
        os.makedirs(work, exist_ok=True)
        prompt = self.tg.send_message(
            chat_id, '새 책 자료를 이 메시지에 답장으로 보내 주세요.\n'
                     '• 보도자료와 표지 이미지는 "파일"로 보내 주세요 (20MB까지)\n'
                     '• 드라이브 폴더 링크를 보내셔도 돼요\n• 다 보냈으면 "완료"라고 답장해 주세요', reply_to=message_id)
        IntakeSource.objects.create(kind=IntakeSource.TELEGRAM, title=f'텔레그램 자료 ({actor})', local_dir=work,
                                    path=f"tg:{chat_id}:{prompt['message_id']}", requested_chat_id=chat_id)

    def _download(self, msg, dest_dir):
        doc = msg.get('document')
        if doc:
            if doc.get('file_size', 0) > MAX_TG_FILE:
                raise ValueError('20MB가 넘는 파일은 드라이브 링크로 보내 주세요')
            name = unicodedata.normalize('NFC', os.path.basename(doc.get('file_name') or f"file-{msg['message_id']}"))
            return self.tg.download_file(doc['file_id'], os.path.join(dest_dir, name))
        if msg.get('photo'):
            return self.tg.download_file(msg['photo'][-1]['file_id'], os.path.join(dest_dir, f"photo-{msg['message_id']}.jpg"))
        return None

    def collect_newbook(self, src, msg, text):
        chat_id = msg['chat']['id']
        folder = parse_folder_id(text)
        if folder:
            src.status = IntakeSource.IGNORED
            src.save(update_fields=['status', 'updated_at'])
            return self.ingest_folder(chat_id, folder)
        try:
            path = self._download(msg, src.local_dir)
        except ValueError as e:
            return self.tg.send_message(chat_id, str(e), reply_to=msg['message_id'])
        if path:
            self.tg.send_message(chat_id, f'📎 {os.path.basename(path)} 받았어요', reply_to=msg['message_id'])
        if text in DONE_WORDS:
            src.status = IntakeSource.QUEUED
            src.save(update_fields=['status', 'updated_at'])
            self.tg.send_message(chat_id, '초안을 만들고 있어요. 1~2분 정도 걸려요.', reply_to=msg['message_id'])

    def on_draft_reply(self, draft, msg, text, actor):
        chat_id = msg['chat']['id']
        if msg.get('photo') or (msg.get('document') or {}).get('mime_type', '').startswith('image/'):
            path = self._download(msg, drafts._draft_dir(draft))
            draft = drafts.replace_front_cover(draft.id, path, actor)
            self.refresh_draft_message(draft)
            return self.tg.send_message(chat_id, '앞표지를 이 사진으로 바꿨어요', reply_to=msg['message_id'])
        if not text:
            return
        self.tg.send_typing(chat_id)
        self.tg.send_message(chat_id, '✍️ 수정 중이에요…', reply_to=msg['message_id'])
        try:
            patch = drafts.propose_patch(draft, text, actor, self.llm)
        except LLMError as e:
            self.notify_admin(f'⚠️ 수정 요청 처리 실패 (초안 #{draft.id}): {e}')
            return self.tg.send_message(chat_id, '지금은 수정 요청을 처리하지 못했어요. 잠시 후 다시 답장해 주세요.',
                                        reply_to=msg['message_id'])
        if not patch.changes and not patch.questions:
            return self.tg.send_message(chat_id, '바꿀 내용을 찾지 못했어요. 조금 더 구체적으로 적어 주세요.',
                                        reply_to=msg['message_id'])
        sent = self.tg.send_message(chat_id, messages.patch_text(drafts.book_snapshot(draft.book), patch.changes,
                                                                 patch.questions),
                                    reply_to=msg['message_id'],
                                    buttons=messages.patch_buttons(patch.id) if patch.changes else None)
        patch.message_id = sent['message_id']
        patch.save(update_fields=['message_id', 'updated_at'])

    # ---- 버튼 ----
    def on_callback(self, cq):
        chat_id = cq['message']['chat']['id']
        if not self.chat_kind(chat_id):
            return self.tg.answer_callback(cq['id'])
        action, args = messages.parse_callback(cq.get('data'))
        try:
            text = self.dispatch_callback(action, args, chat_id, cq, cq.get('from', {}).get('first_name', '')) or ''
        except (drafts.StaleError, drafts.PatchError) as e:
            text = str(e)
        except PublishBlocked as e:
            text = ('공개를 막는 항목이 있어요: ' + ', '.join(w['message'] for w in e.warnings)) if e.warnings else '공개할 수 없는 상태예요'
        self.tg.answer_callback(cq['id'], text)

    def dispatch_callback(self, action, args, chat_id, cq, actor):
        if action == 'noop':
            return '취소했어요'
        if action in ('pub', 'del'):
            draft = BookDraft.objects.select_related('book').get(pk=args[0])
            question = '사이트에 공개할까요?' if action == 'pub' else '이 초안을 폐기할까요?'
            self.tg.send_message(chat_id, f"'{draft.book.title}' {question}", buttons=messages.confirm_buttons(action, *args))
            return ''
        if action == 'pubok':
            if WorkerState.get('mode', 'admin_only') != 'live':
                return '리허설 모드라 공개하지 않았어요'
            draft = publish(args[0], args[1])
            self.refresh_draft_message(draft)
            self._fill_notion(draft)
            self.tg.send_message(chat_id, f"✅ 공개했어요: {settings.SITE_URL}/book={draft.book.id}")
            return '공개했어요'
        if action == 'delok':
            draft = drafts.discard(args[0], args[1])
            if draft.message_id:
                self._edit(draft, '🗑 폐기된 초안이에요')
            return '폐기했어요'
        if action == 'img':
            draft = drafts.cycle_3d(args[0], args[1], actor)
            with open(draft.files['cover_3d_options'][draft.files['cover_3d_index']], 'rb') as fh:
                self.tg.send_photo(chat_id, fh.read(), '입체 이미지를 이걸로 바꿨어요', reply_to=draft.message_id)
            self.refresh_draft_message(draft)
            return '바꿨어요'
        if action == 'apply':
            draft, rev = drafts.apply_patch(args[0], actor)
            self.refresh_draft_message(draft)
            self.tg.send_message(chat_id, '반영했어요', reply_to=cq['message']['message_id'],
                                 buttons=messages.undo_buttons(rev.id))
            return '반영했어요'
        if action == 'cancel':
            PendingPatch.objects.filter(pk=args[0], status=PendingPatch.PROPOSED).update(status=PendingPatch.CANCELLED)
            return '취소했어요'
        if action == 'undo':
            draft, _ = drafts.revert_revision(args[0], actor)
            self.refresh_draft_message(draft)
            return '되돌렸어요'
        return ''

    def _fill_notion(self, draft):
        if not (self.notion and WorkerState.get('notion_write', False)):
            return
        try:
            r = fill_notion_row(self.notion, self.config['NOTION_DATA_SOURCE_ID'], draft.book,
                                draft.extracted.get('_isbn_addon', ''), settings.SITE_URL)
        except Exception as e:  # 노션 실패는 공개를 되돌리지 않는다
            return self.notify_admin(f'⚠️ 노션 기입 실패 (초안 #{draft.id}): {e}')
        if r['page_id']:
            draft.notion_page_id = r['page_id']
            draft.save(update_fields=['notion_page_id', 'updated_at'])
        if r['note']:
            self.notify_admin(r['note'])
