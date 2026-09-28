"""텔레그램 업데이트 처리. 권한은 대화방 단위: 등록된 검수 그룹과 관리자 1:1 방만 응답한다."""
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone as dt_timezone
from typing import Protocol

from django.conf import settings
from django.utils import timezone

from books.preview import preview_url
from context import record as context_record, stats as context_stats
from intake import drafts, funding, messages, notices, review
from intake.llm import LLMError
from intake.models import BookDraft, FundingCampaign, IntakeSource, PendingPatch, ReviewItem, TelegramChat, WorkerState
from intake.notion import fill_notion_row
from intake.publish import PublishBlocked, publish
from marketing.bot import COMMANDS as MARKETING_COMMANDS, Marketing
from web.models import Notice

log = logging.getLogger('intake')
FOLDER_RE = re.compile(r'drive\.google\.com/(?:drive/(?:u/\d+/)?folders/|open\?id=)([\w-]{10,})')
ADMIN_COMMANDS = ('/status', '/mode', '/drive', '/notion', '/baseline', '/ingest', '/retry', '/fund', '/ctx')
DONE_WORDS = ('완료', '끝', '다 보냈어요', '다보냈어요')
MAX_TG_FILE = 20 * 1024 * 1024
REPLY_GUIDE = '이 메시지에는 답장으로 고칠 수 있는 게 없어요. 책 초안(📕), 알림 띠, 홍보 초안 메시지에 답장해 주세요.'
FORGET_COMMANDS = ('/잊어', '/forget')
UNRECORDED_COMMANDS = FORGET_COMMANDS + ('/register', '/start')   # /register 에는 초대 코드가 붙는다
CONTEXT_ANNOUNCE = ('이제부터 이 방 대화를 봇이 기록해요. 전화번호·계좌·비밀번호·주소는 가린 채 저장하고, 90일이 지나면 지워요. '
                    '새 소식이나 행사를 놓치지 않고 홍보 초안에 반영하는 데만 써요. 기록에서 빼고 싶은 메시지가 있으면 '
                    '텔레그램에서 지우기 전에 그 메시지에 답장으로 /잊어 라고 적어 주시거나 개발자에게 말씀해 주세요.')


def parse_folder_id(text):
    m = FOLDER_RE.search(text or '')
    return m.group(1) if m else None


def _sent_at(message):
    return datetime.fromtimestamp(message['date'], tz=dt_timezone.utc) if message.get('date') else None


def split_command(text):
    if not text.startswith('/'):
        return '', text
    head, _, arg = text.partition(' ')
    return head.split('@')[0].lower(), arg.strip()


class DriveOps(Protocol):
    def baseline(self) -> int: ...
    def ingest(self, folder_id: str) -> IntakeSource: ...


class Bot:
    def __init__(self, tg, llm, notion=None, drive_ops=None, config=None, fund_get=None):
        self.tg, self.llm, self.notion, self.drive_ops = tg, llm, notion, drive_ops
        self.config = config or settings.INTAKE
        self.fund_get = fund_get   # 테스트에서 가짜 페이지를 넣는다. 기본은 funding.http_get
        self.marketing = Marketing(tg, llm, self)

    # ---- 방 ----
    def chat_kind(self, chat_id):
        return TelegramChat.objects.filter(chat_id=chat_id).values_list('kind', flat=True).first()

    def _chat(self, kind):
        return TelegramChat.objects.filter(kind=kind).order_by('-id').values_list('chat_id', flat=True).first()

    def review_chat_id(self):
        group = self._chat(TelegramChat.REVIEWERS)
        return group if WorkerState.get('mode', 'admin_only') == 'live' and group else self._chat(TelegramChat.ADMIN)

    def notify_admin(self, text):
        admin = self._chat(TelegramChat.ADMIN)
        if admin:
            self.tg.send_message(admin, text)

    def notify_reviewers_or_admin(self, text):
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
                self.record_context(update['message'])
                self.on_message(update['message'])
            elif 'edited_message' in update:
                self.record_context(update['edited_message'], edited=True)
        except Exception as e:  # 한 업데이트의 실패가 워커를 멈추지 않게
            log.exception('update failed')
            self.notify_admin(f'⚠️ 업데이트 처리 오류: {type(e).__name__}: {e}')

    def record_context(self, msg, edited=False):
        """검수 방 대화를 가린 채 기록한다(켜져 있을 때만). 실패해도 원래 처리는 계속한다."""
        try:
            if not WorkerState.get('context_record', False):
                return
            if self.chat_kind(msg['chat']['id']) != TelegramChat.REVIEWERS:
                return
            if split_command((msg.get('text') or '').strip())[0] in UNRECORDED_COMMANDS:
                return
            if edited:
                context_record.apply_edit(msg)
            else:
                context_record.record_telegram(msg)
        except Exception as e:  # 기록 때문에 초안 답장·명령이 막히면 안 된다
            log.exception('context record failed')
            today = timezone.now().astimezone(notices.KST).date().isoformat()
            if WorkerState.get('context_error_notified') != today:
                WorkerState.put('context_error_notified', today)
                self.notify_admin(f'⚠️ 대화 기록 오류(오늘은 더 알리지 않아요): {type(e).__name__}: {e}')

    def on_message(self, msg):
        chat = msg['chat']
        chat_id = chat['id']
        text = (msg.get('text') or msg.get('caption') or '').strip()
        actor = msg.get('from', {}).get('first_name', '')
        cmd, arg = split_command(text)
        if cmd == '/start' and chat.get('type') == 'private':
            return self.register(chat, TelegramChat.ADMIN, arg)
        if cmd == '/register' and chat.get('type') in ('group', 'supergroup'):
            return self.register(chat, TelegramChat.REVIEWERS, arg)
        kind = self.chat_kind(chat_id)
        if not kind:
            return
        if kind == TelegramChat.REVIEWERS and cmd in FORGET_COMMANDS:
            return self.forget_context(chat_id, msg)
        if kind == TelegramChat.ADMIN and cmd in ADMIN_COMMANDS:
            return self.admin_command(chat_id, cmd, arg)
        if kind == TelegramChat.ADMIN and cmd in MARKETING_COMMANDS:
            return self.marketing.admin_command(chat_id, cmd, arg)
        if cmd == '/notice':
            return self.start_notice(chat_id, msg['message_id'], actor)
        if cmd == '/newbook':
            return self.start_newbook(chat_id, msg['message_id'], actor)
        reply = msg.get('reply_to_message')
        if reply:
            src = IntakeSource.objects.filter(path=f"tg:{chat_id}:{reply['message_id']}", status=IntakeSource.SEEN).first()
            if src:
                return self.collect_newbook(src, msg, text)
            item = ReviewItem.objects.filter(chat_id=chat_id, message_id=reply['message_id']).first()
            if item and text:
                return self.on_review_reply(item, msg, text, actor)
            notice = Notice.objects.filter(chat_id=chat_id, message_id=reply['message_id']) \
                .exclude(state=Notice.REMOVED).first()
            if notice and text:
                return self.on_notice_reply(notice, msg, text, actor)
            if self.marketing.owns_message(chat_id, reply['message_id']):
                return self.marketing.handle_reply(chat_id, reply['message_id'], msg, text, actor)
            draft = BookDraft.objects.filter(chat_id=chat_id, message_id=reply['message_id']).select_related('book').first()
            if draft is None:
                patch = PendingPatch.objects.filter(message_id=reply['message_id'], draft__chat_id=chat_id) \
                    .select_related('draft__book').first()
                draft = patch.draft if patch else None      # "이렇게 바꿀게요"에 단 답장도 같은 초안의 수정 요청
            if draft and draft.book and draft.state in (BookDraft.REVIEW, BookDraft.PUBLISHED):
                return self.on_draft_reply(draft, msg, text, actor)
        if kind == TelegramChat.ADMIN and parse_folder_id(text):
            return self.ingest_folder(chat_id, parse_folder_id(text))
        if reply and kind == TelegramChat.REVIEWERS and reply.get('from', {}).get('is_bot'):
            # 봇이 보낸 메시지에 단 답장에만 안내한다. privacy mode 를 끄면 사람끼리 주고받는 답장도 들어오는데, 거기엔 끼어들지 않는다.
            # 내린 알림 카드·지난 카드에 단 답장도 여기로 온다 → 책 초안에 한정하지 않는 문구
            return self.tg.send_message(chat_id, REPLY_GUIDE, reply_to=msg['message_id'])

    def forget_context(self, chat_id, msg):
        reply = msg.get('reply_to_message')
        if not reply:
            text = '지울 메시지에 답장으로 /잊어 라고 적어 주세요. 잘 안 되면 개발자에게 말씀해 주세요.'
        elif context_record.forget(chat_id, reply['message_id'], sent_at=_sent_at(reply)):
            text = '기록에서 지웠어요. 텔레그램 메시지는 직접 지워 주세요.'
        else:
            text = '찾지 못했어요. 예전 대화라면 개발자에게 말씀해 주세요.'
        self.tg.send_message(chat_id, text, reply_to=msg['message_id'])

    def register(self, chat, kind, code):
        expected = self.config.get('TELEGRAM_INVITE_CODE')
        if not expected or code != expected:
            return
        TelegramChat.objects.update_or_create(chat_id=chat['id'], defaults={'kind': kind, 'title': chat.get('title', '')})
        self.tg.send_message(chat['id'], '등록됐어요. 새 책 초안이 준비되면 여기로 알려 드릴게요.' if kind == TelegramChat.REVIEWERS
                             else '관리자 방으로 등록됐어요. /status 로 상태를 볼 수 있어요.')

    def admin_command(self, chat_id, cmd, arg):
        if cmd == '/status':
            queued = IntakeSource.objects.filter(status=IntakeSource.QUEUED).count()
            in_review = BookDraft.objects.filter(state=BookDraft.REVIEW).count()
            asks = ReviewItem.objects.filter(status=ReviewItem.PENDING).count()
            text = (f"mode={WorkerState.get('mode', 'admin_only')} drive={WorkerState.get('drive_autoscan', False)} "
                    f"notion={WorkerState.get('notion_write', False)}\n대기 {queued}건 · 검수 중 {in_review}건 · "
                    f"확인 부탁 {asks}건 · 마지막 드라이브 확인 {WorkerState.get('last_drive_scan', '-')}")
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
        elif cmd == '/fund':
            if arg in ('on', 'off'):
                WorkerState.put('fund_autoscan', arg == 'on')
                text = f'fund={arg}'
            elif arg in ('auto', 'confirm'):
                WorkerState.put('fund_mode', arg)
                text = f'fund_mode={arg}'
            elif arg == 'now':
                text = f'북펀드 확인을 마쳤어요. 새로 찾은 펀딩 {len(self.run_fund_scan())}건'
            else:
                ours = FundingCampaign.objects.filter(is_ours=True).order_by('-id')[:5]
                head = (f"fund={'on' if WorkerState.get('fund_autoscan', True) else 'off'} "
                        f"mode={WorkerState.get('fund_mode', 'auto')} 마지막 확인 {WorkerState.get('last_fund_scan', '-')}")
                text = '\n'.join([head] + [f'• {c.get_platform_display()} {c.title} {c.url}' for c in ours])
        elif cmd == '/ctx':
            if arg in ('on', 'off'):
                WorkerState.put('context_record', arg == 'on')
                text = f'ctx={arg}'
            elif arg == 'announce':
                group = self._chat(TelegramChat.REVIEWERS)
                if group:
                    self.tg.send_message(group, CONTEXT_ANNOUNCE)
                    text = '검수 방에 안내를 보냈어요'
                else:
                    text = '검수 방이 등록돼 있지 않아요'
            else:
                state = 'on' if WorkerState.get('context_record', False) else 'off'
                text = '\n'.join([f'ctx={state}'] + context_stats.summary_lines(timezone.now()))
        else:
            text = ('사용법: /status · /mode live|admin_only · /drive on|off · /notion on|off · /baseline · '
                    '/ingest <폴더 링크> · /retry <번호> · /fund [on|off|auto|confirm|now] · /ctx [on|off|announce]')
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
        if patch.cancelled_previous:
            return self.tg.send_message(chat_id, patch.reply_message or '알겠어요. 진행 중이던 수정 요청을 취소했어요.',
                                        reply_to=msg['message_id'])
        if not patch.changes and not patch.questions:
            return self.tg.send_message(chat_id, patch.reply_message or '바꿀 내용을 찾지 못했어요. 조금 더 구체적으로 적어 주세요.',
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
        if (cq.get('data') or '').startswith('mk:'):
            actor = cq.get('from', {}).get('first_name', '')
            return self.tg.answer_callback(cq['id'], self.marketing.handle_callback(cq['data'], chat_id, cq, actor) or '')
        action, args = messages.parse_callback(cq.get('data'))
        try:
            text = self.dispatch_callback(action, args, chat_id, cq, cq.get('from', {}).get('first_name', '')) or ''
        except (drafts.StaleError, drafts.PatchError, review.ReviewError, notices.NoticeError) as e:
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
        if action == 'rv':
            return self.choose_review(args[0], args[1], actor)
        if action == 'rvu':
            self.refresh_review_message(review.undo(args[0], actor, self.notion))
            return '다시 고를 수 있어요'
        if action in ('ntpub', 'nton'):
            notice = notices.set_state(args[0], Notice.POSTED)
            self._refresh_notice(notice)
            self.tg.send_message(chat_id, f'✅ 첫 화면에 띄웠어요: {settings.SITE_URL}', reply_to=notice.message_id)
            return '게시했어요'
        if action in ('ntdel', 'ntoff'):
            notice = notices.set_state(args[0], Notice.REMOVED)
            self._refresh_notice(notice)
            return '취소했어요' if action == 'ntdel' else '내렸어요'
        if action == 'ntok':
            notice = notices.apply_pending(args[0])
            self._refresh_notice(notice)
            self.tg.send_message(chat_id, f'✅ 첫 화면 알림을 바꿨어요: {settings.SITE_URL}', reply_to=notice.message_id,
                                 buttons=messages.notice_undo_buttons(notice))
            return '반영했어요'
        if action == 'ntno':
            self._refresh_notice(notices.discard_pending(args[0]))
            return '취소했어요'
        if action == 'ntundo':
            self._refresh_notice(notices.undo(args[0], args[1] if len(args) > 1 else None))
            return '되돌렸어요'
        return ''

    # ---- 확인 부탁 ----
    def refresh_review_message(self, item):
        if item.message_id:
            total = ReviewItem.objects.filter(batch=item.batch).count()
            self.tg.edit_text(item.chat_id, item.message_id, messages.review_text(item, total),
                              messages.review_buttons(item))

    def choose_review(self, item_id, index, actor):
        try:
            item, _ = review.choose(item_id, index, actor, self.notion)
        except review.ReviewError as e:
            if e.stale:
                item = ReviewItem.objects.get(pk=item_id)
                self.refresh_review_message(item)
                self.notify_admin(f'⏸ 확인 부탁 {item.seq} {item.title}: 게시 뒤 값이 바뀌어 반영하지 않았어요 (#{item.id})')
            raise
        self.refresh_review_message(item)
        if not ReviewItem.objects.filter(batch=item.batch, status=ReviewItem.PENDING).exists():
            done = ReviewItem.objects.filter(batch=item.batch)
            self.notify_admin(f"확인 부탁 '{item.batch}' 모두 끝났어요: 반영 {done.filter(status=ReviewItem.APPLIED).count()} · "
                              f"그대로 {done.filter(status=ReviewItem.KEPT).count()} · "
                              f"중단 {done.filter(status=ReviewItem.STALE).count()}")
        return '반영했어요' if item.status == ReviewItem.APPLIED else '그대로 두었어요'

    def on_review_reply(self, item, msg, text, actor):
        item.note = f'{item.note}\n{actor}: {text}'.strip()
        item.save(update_fields=['note', 'updated_at'])
        self.notify_admin(f'📝 확인 부탁 {item.seq} {item.title}\n{actor}: {text}')
        self.tg.send_message(msg['chat']['id'], '메모 남겼어요. 확인해서 반영할게요.', reply_to=msg['message_id'])

    # ---- 알림 띠 ----
    def start_notice(self, chat_id, message_id, actor):
        live = Notice.objects.active().first()
        if live:
            sent = self.tg.send_message(chat_id, messages.notice_card(live), buttons=messages.notice_buttons(live))
            notices.attach_message(live, chat_id, sent['message_id'])
        prompt = self.tg.send_message(chat_id, messages.NOTICE_PROMPT, reply_to=message_id)
        notices.start(chat_id, prompt['message_id'], actor)

    def on_notice_reply(self, notice, msg, text, actor):
        chat_id = msg['chat']['id']
        self.tg.send_typing(chat_id)
        try:
            warnings = notices.fill_from_text(notice, text, self.llm)
        except LLMError as e:
            self.notify_admin(f'⚠️ 알림 띠 요청 처리 실패: {e}')
            return self.tg.send_message(chat_id, '지금은 알림을 만들지 못했어요. 잠시 후 다시 답장해 주세요.',
                                        reply_to=msg['message_id'])
        except notices.NoticeError as e:
            return self.tg.send_message(chat_id, str(e), reply_to=msg['message_id'])
        sent = self.tg.send_message(chat_id, messages.notice_card(notice, warnings), reply_to=msg['message_id'],
                                    buttons=messages.notice_buttons(notice))
        notices.attach_message(notice, chat_id, sent['message_id'])

    def _refresh_notice(self, notice):
        if notice.chat_id and notice.message_id:
            self.tg.edit_text(notice.chat_id, notice.message_id, messages.notice_card(notice),
                              buttons=messages.notice_buttons(notice))

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

    # ---- 북펀드 ----
    def run_fund_scan(self, now=None):
        now = now or timezone.now()
        result = funding.scan(get=self.fund_get or funding.http_get, now=now)
        if result.errors:
            today = now.astimezone(notices.KST).date().isoformat()
            if WorkerState.get('fund_error_day') != today:
                WorkerState.put('fund_error_day', today)
                self.notify_admin('⚠️ 북펀드 확인 실패: ' + ', '.join(result.errors)
                                  + '\n그동안은 /notice 로 직접 올려 주세요.')
        for camp in result.new:
            self.announce_campaign(camp, now)
        return result.new

    def announce_campaign(self, camp, now=None):
        confirm = WorkerState.get('fund_mode', 'auto') == 'confirm'
        notice = notices.from_campaign(camp, now, post=not confirm)
        chat = self.review_chat_id()
        if chat:
            head = ('📣 새 북펀드를 찾았어요. 첫 화면 알림으로 올릴까요?' if confirm
                    else '📣 새 북펀드를 찾아 사이트 첫 화면에 알림을 올렸어요')
            sent = self.tg.send_message(chat, messages.notice_card(notice, head=head),
                                        buttons=messages.notice_buttons(notice))
            notices.attach_message(notice, chat, sent['message_id'])
        return notice
