import json
import os
import tempfile
from datetime import date
from unittest import mock

from django.test import TestCase, override_settings
from PIL import Image

from books.models import Book, Category
from context.models import ContextEntry
from intake import drafts
from intake.bot import Bot, parse_folder_id
from intake.models import BookDraft, IntakeSource, PendingPatch, TelegramChat, WorkerState

WORK = tempfile.mkdtemp()
CONFIG = {'TELEGRAM_INVITE_CODE': 'letmein', 'WORK_DIR': WORK, 'NOTION_DATA_SOURCE_ID': 'ds'}
ADMIN, GROUP = 100, -200
GUIDE = '이 메시지에는 답장으로 고칠 수 있는 게 없어요. 책 초안(📕), 알림 띠, 홍보 초안 메시지에 답장해 주세요.'


class FakeTG:
    def __init__(self):
        self.calls, self.next_id = [], 1000

    def _msg(self):
        self.next_id += 1
        return {'message_id': self.next_id}

    def send_message(self, chat_id, text, reply_to=None, buttons=None, html=False):
        self.calls.append(('send', chat_id, text, buttons))
        return self._msg()

    def send_photo(self, chat_id, photo, caption, buttons=None, reply_to=None):
        self.calls.append(('photo', chat_id, caption, buttons))
        return self._msg()

    def edit_caption(self, chat_id, message_id, caption, buttons=None):
        self.calls.append(('edit', chat_id, caption, buttons))

    def answer_callback(self, callback_id, text=''):
        self.calls.append(('answer', callback_id, text))

    def send_typing(self, chat_id):
        pass

    def download_file(self, file_id, dest):
        Image.new('RGB', (10, 10)).save(dest, 'JPEG')
        return dest

    def texts(self, kind='send'):
        return [c[2] for c in self.calls if c[0] == kind]


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, user, attachments=()):
        return json.dumps(self.reply, ensure_ascii=False)


def msg(chat_id, text='', reply_to=None, chat_type='group', reply_is_bot=True, **extra):
    m = {'message_id': 1, 'chat': {'id': chat_id, 'type': chat_type, 'title': 't'},
         'from': {'first_name': '검수자A'}, 'text': text}
    if reply_to:
        m['reply_to_message'] = {'message_id': reply_to, 'from': {'is_bot': reply_is_bot}}
    m.update(extra)
    return {'update_id': 1, 'message': m}


def cb(chat_id, data):
    return {'update_id': 2, 'callback_query': {'id': 'q', 'data': data, 'from': {'first_name': '검수자B'},
                                               'message': {'message_id': 555, 'chat': {'id': chat_id}}}}


@override_settings(INTAKE=CONFIG)
class BotTest(TestCase):
    def setUp(self):
        self.tg = FakeTG()
        cat = Category.objects.create(name='에세이')
        book = Book.objects.create(title='무지개를 변호하다', subtitle='삶과 생각', full_price=22000, page_count=264,
                                   category=cat, published_date=date(2026, 6, 1), is_published=False)
        src = IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='x')
        self.draft = BookDraft.objects.create(source=src, book=book, state=BookDraft.REVIEW, chat_id=GROUP,
                                              message_id=777, extracted={'_unresolved': [], '_edited': [], '_notes': [],
                                                                         '_source_quality': 0.9})
        TelegramChat.objects.create(chat_id=ADMIN, kind=TelegramChat.ADMIN)
        TelegramChat.objects.create(chat_id=GROUP, kind=TelegramChat.REVIEWERS)

    def bot(self, reply=None, **kw):
        return Bot(self.tg, FakeLLM(reply or {}), config=CONFIG, **kw)

    def test_parse_folder_id(self):
        self.assertEqual(parse_folder_id('https://drive.google.com/drive/u/0/folders/1UBvHEb7Z0Wx96EaIq?usp=x'),
                         '1UBvHEb7Z0Wx96EaIq')
        self.assertIsNone(parse_folder_id('그냥 문장'))

    def test_register_requires_invite_code(self):
        TelegramChat.objects.all().delete()
        self.bot().handle_update(msg(5, '/start wrong', chat_type='private'))
        self.assertFalse(TelegramChat.objects.exists())
        self.bot().handle_update(msg(5, '/start letmein', chat_type='private'))
        self.assertEqual(TelegramChat.objects.get().kind, TelegramChat.ADMIN)
        self.bot().handle_update(msg(-9, '/register@hantijae_bot letmein'))
        self.assertTrue(TelegramChat.objects.filter(chat_id=-9, kind=TelegramChat.REVIEWERS).exists())

    def test_unregistered_chat_is_ignored(self):
        self.bot().handle_update(msg(-12345, '/status'))
        self.bot().handle_update(cb(-12345, 'pubok:1:1'))
        self.assertEqual([c for c in self.tg.calls if c[0] != 'answer'], [])

    def test_reply_proposes_patch_and_apply_updates_caption(self):
        reply = {'changes': [{'field': 'subtitle', 'new_value': '삶과 싸움'}], 'questions': []}
        self.bot(reply).handle_update(msg(GROUP, '부제는 삶과 싸움이야', reply_to=777))
        self.assertIn('• 부제: 삶과 생각 → 삶과 싸움', self.tg.texts()[-1])
        patch = PendingPatch.objects.get()
        self.bot().handle_update(cb(GROUP, f'apply:{patch.id}'))
        self.assertEqual(Book.objects.get().subtitle, '삶과 싸움')
        self.assertTrue(any(c[0] == 'edit' and '삶과 싸움' in c[2] for c in self.tg.calls))
        self.assertEqual(self.tg.calls[-1], ('answer', 'q', '반영했어요'))

    def test_stale_callback_answers_with_message(self):
        self.bot().handle_update(cb(GROUP, f'img:{self.draft.id}:{self.draft.version + 3}'))
        self.assertIn('다른 분이', self.tg.calls[-1][2])

    def test_publish_is_blocked_in_admin_only_mode(self):
        self.bot().handle_update(cb(GROUP, f'pubok:{self.draft.id}:{self.draft.version}'))
        self.assertIn('리허설', self.tg.calls[-1][2])
        self.assertFalse(Book.objects.get().is_published)

    def test_publish_in_live_mode_fills_notion(self):
        WorkerState.put('mode', 'live')
        WorkerState.put('notion_write', True)
        notion = mock.Mock()
        with mock.patch('intake.publish.check_book', return_value=[]), \
                mock.patch('intake.bot.fill_notion_row', return_value={'page_id': 'p1', 'filled': ['ISBN'], 'note': ''}) as fill:
            Bot(self.tg, FakeLLM({}), notion=notion, config=CONFIG).handle_update(
                cb(GROUP, f'pubok:{self.draft.id}:{self.draft.version}'))
        self.assertTrue(Book.objects.get().is_published)
        fill.assert_called_once()
        self.assertEqual(BookDraft.objects.get().notion_page_id, 'p1')

    def test_newbook_collects_files_then_queues(self):
        bot = self.bot()
        bot.handle_update(msg(GROUP, '/newbook'))
        prompt_id = self.tg.next_id
        src = IntakeSource.objects.get(kind=IntakeSource.TELEGRAM)
        bot.handle_update(msg(GROUP, '', reply_to=prompt_id,
                              document={'file_id': 'f1', 'file_name': '보도자료_새책.pdf', 'file_size': 1000}))
        self.assertTrue(os.path.exists(os.path.join(src.local_dir, '보도자료_새책.pdf')))
        bot.handle_update(msg(GROUP, '완료', reply_to=prompt_id))
        self.assertEqual(IntakeSource.objects.get(pk=src.pk).status, IntakeSource.QUEUED)

    def test_admin_link_triggers_ingest(self):
        ops = mock.Mock()
        ops.ingest.return_value = IntakeSource(title='보도자료_새책')
        self.bot(drive_ops=ops).handle_update(
            msg(ADMIN, 'https://drive.google.com/drive/folders/1AbCdEfGhIjK', chat_type='private'))
        ops.ingest.assert_called_once_with('1AbCdEfGhIjK')

    def test_marketing_admin_command_is_routed(self):
        self.bot().handle_update(msg(ADMIN, '/mk admin_only', chat_type='private'))
        self.assertEqual(WorkerState.get('marketing_mode'), 'admin_only')

    def test_mk_callback_is_delegated(self):
        from marketing.models import Draft, Proposal
        p = Proposal.objects.create(kind=Proposal.KIT, book=self.draft.book, headline='h')
        d = Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='인스타 본문')
        self.bot().handle_update(cb(GROUP, f'mk:v:{d.id}'))
        self.assertIn('인스타 본문', self.tg.texts()[0])

    def test_reply_to_marketing_draft_routes_to_rewrite(self):
        from marketing.models import Draft, Proposal
        p = Proposal.objects.create(kind=Proposal.KIT, book=self.draft.book, headline='h')
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='원래 글', chat_id=GROUP, message_id=4343)
        self.bot({'title': '', 'body': '고친 글', 'note': '고쳤어요'}).handle_update(msg(GROUP, '짧게요', reply_to=4343))
        self.assertTrue(Draft.objects.filter(body='고친 글', version=2).exists())


class StrictFakeTG(FakeTG):
    """텔레그램처럼 텍스트 메시지에 editMessageCaption을 거절한다."""
    def __init__(self):
        super().__init__()
        self.kinds = {}

    def _msg(self, kind='text'):
        m = super()._msg()
        self.kinds[m['message_id']] = kind
        return m

    def send_message(self, chat_id, text, reply_to=None, buttons=None, html=False):
        self.calls.append(('send', chat_id, text, buttons))
        return self._msg('text')

    def send_photo(self, chat_id, photo, caption, buttons=None, reply_to=None):
        self.calls.append(('photo', chat_id, caption, buttons))
        return self._msg('photo')

    def edit_caption(self, chat_id, message_id, caption, buttons=None):
        from intake.telegram_api import TelegramError
        if self.kinds.get(message_id) == 'text':
            raise TelegramError('editMessageCaption: Bad Request: there is no caption in the message to edit')
        self.calls.append(('edit', chat_id, caption, buttons))

    def edit_text(self, chat_id, message_id, text, buttons=None, html=False):
        from intake.telegram_api import TelegramError
        if self.kinds.get(message_id) == 'photo':
            raise TelegramError('editMessageText: Bad Request: there is no text in the message to edit')
        self.calls.append(('edit_text', chat_id, text, buttons))


@override_settings(INTAKE=CONFIG)
class BotRealTelegramRulesTest(TestCase):
    def setUp(self):
        self.tg = StrictFakeTG()
        cat = Category.objects.create(name='에세이')
        book = Book.objects.create(title='표지 없는 책', full_price=1, page_count=10, category=cat,
                                   published_date=date(2026, 1, 1), is_published=False)
        src = IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='x')
        self.draft = BookDraft.objects.create(source=src, book=book, state=BookDraft.REVIEW,
                                              extracted={'_unresolved': [], '_edited': [], '_notes': [],
                                                         '_source_quality': 0.9})
        TelegramChat.objects.create(chat_id=ADMIN, kind=TelegramChat.ADMIN)
        TelegramChat.objects.create(chat_id=GROUP, kind=TelegramChat.REVIEWERS)
        WorkerState.put('mode', 'live')

    def test_coverless_draft_can_be_fixed_by_photo_reply(self):
        bot = Bot(self.tg, FakeLLM({}), config=CONFIG)
        bot.notify_draft(self.draft)                                   # 표지 없음 → 텍스트 메시지
        draft_msg = BookDraft.objects.get().message_id
        bot.handle_update(msg(GROUP, '', reply_to=draft_msg, photo=[{'file_id': 'p1'}]))
        self.assertTrue(Book.objects.get().cover_image)
        self.assertIn('앞표지를 이 사진으로 바꿨어요', self.tg.texts())
        self.assertFalse([t for t in self.tg.texts() if '오류' in t])

    def test_reply_to_patch_proposal_starts_a_new_patch_for_the_same_draft(self):
        reply = {'changes': [{'field': 'subtitle', 'new_value': '새 부제'}], 'questions': []}
        bot = Bot(self.tg, FakeLLM(reply), config=CONFIG)
        bot.notify_draft(self.draft)
        bot.handle_update(msg(GROUP, '부제 바꿔줘', reply_to=BookDraft.objects.get().message_id))
        proposal_id = PendingPatch.objects.get().message_id
        bot.handle_update(msg(GROUP, '아, 그리고 부제는 새 부제로', reply_to=proposal_id))
        self.assertEqual(PendingPatch.objects.count(), 2)

    def test_reply_to_other_bot_message_gets_guidance(self):
        bot = Bot(self.tg, FakeLLM({}), config=CONFIG)
        sent = self.tg.send_message(GROUP, '반영했어요')
        bot.handle_update(msg(GROUP, '고마워', reply_to=sent['message_id']))
        self.assertEqual(self.tg.texts()[-1], GUIDE)

    def test_reply_to_human_message_is_ignored(self):
        # privacy mode 를 끄면 사람끼리 주고받는 답장도 봇에 들어온다 → 끼어들지 않는다
        Bot(self.tg, FakeLLM({}), config=CONFIG).handle_update(
            msg(GROUP, '저도 그렇게 생각해요', reply_to=4242, reply_is_bot=False))
        self.assertEqual(self.tg.calls, [])

    def test_reply_to_removed_notice_card_gets_generic_guidance(self):
        from web.models import Notice
        Notice.objects.create(message='지난 알림', chat_id=GROUP, message_id=4444, state=Notice.REMOVED)
        Bot(self.tg, FakeLLM({}), config=CONFIG).handle_update(msg(GROUP, '다시 올려 주세요', reply_to=4444))
        self.assertEqual(self.tg.texts()[-1], GUIDE)


@override_settings(INTAKE=CONFIG)
class CancelFlowTest(TestCase):
    setUp = BotTest.setUp

    def test_cancel_understood_from_context_closes_open_patches(self):
        PendingPatch.objects.create(draft=self.draft, base_version=1, changes=[{'field': 'subtitle', 'new_value': 'x'}],
                                    request_text='부제 바꿔줘')
        reply = {'changes': [], 'questions': [], 'cancel_previous': True, 'message': '알겠어요, 부제 변경은 취소할게요.'}
        Bot(self.tg, FakeLLM(reply), config=CONFIG).handle_update(msg(GROUP, '취소', reply_to=777))
        self.assertEqual(set(PendingPatch.objects.values_list('status', flat=True)), {PendingPatch.CANCELLED})
        self.assertEqual(self.tg.texts()[-1], '알겠어요, 부제 변경은 취소할게요.')


DATE = 1790000000


@override_settings(INTAKE=CONFIG)
class ContextRecordTest(TestCase):
    setUp = BotTest.setUp
    bot = BotTest.bot

    def on(self):
        WorkerState.put('context_record', True)

    def test_group_message_is_recorded_only_when_on(self):
        self.bot().handle_update(msg(GROUP, '연락처 010-1234-5678', date=DATE))
        self.assertFalse(ContextEntry.objects.exists())
        self.on()
        self.bot().handle_update(msg(GROUP, '연락처 010-1234-5678', date=DATE))
        self.assertEqual(ContextEntry.objects.get().text, '연락처 [전화]')

    def test_admin_chat_is_not_recorded(self):
        self.on()
        self.bot().handle_update(msg(ADMIN, '/status', chat_type='private', date=DATE))
        self.assertFalse(ContextEntry.objects.exists())

    def test_record_failure_does_not_block_routing_and_alerts_admin_once(self):
        self.on()
        with mock.patch('context.record.record_telegram', side_effect=RuntimeError('db down')):
            self.bot().handle_update(msg(GROUP, '이거요', reply_to=4242, date=DATE))
            self.bot().handle_update(msg(GROUP, '이거요', reply_to=4242, date=DATE))
        self.assertEqual(self.tg.texts().count(GUIDE), 2)
        self.assertEqual(sum('대화 기록 오류' in t for t in self.tg.texts()), 1)

    def test_edited_message_updates_record_without_routing(self):
        self.on()
        self.bot().handle_update(msg(GROUP, '처음 글', date=DATE))
        edited = msg(GROUP, '고친 글 010-1234-5678', date=DATE, edit_date=DATE + 60)['message']
        self.bot().handle_update({'update_id': 3, 'edited_message': edited})
        self.assertEqual(ContextEntry.objects.get().text, '고친 글 [전화]')
        self.assertEqual(self.tg.calls, [])

    def test_forget_reply_deletes_record_and_is_not_itself_recorded(self):
        self.on()
        bot = self.bot()
        bot.handle_update(msg(GROUP, '지울 글', date=DATE))
        forget = msg(GROUP, '/잊어', reply_to=1, date=DATE)
        forget['message']['message_id'] = 2
        bot.handle_update(forget)
        entry = ContextEntry.objects.get()          # /잊어 메시지 자체는 기록되지 않아 한 줄뿐
        self.assertEqual((entry.message_id, entry.forgotten, entry.text), (1, True, ''))
        self.assertEqual(self.tg.texts()[-1], '기록에서 지웠어요. 텔레그램 메시지는 직접 지워 주세요.')

    def test_forget_drops_moments_built_on_that_message(self):
        from marketing.models import Signal, SignalEvidence
        self.on()
        bot = self.bot()
        bot.handle_update(msg(GROUP, '금요일 강연', date=DATE))
        s = Signal.objects.create(kind=Signal.MOMENT, key='moment:x', title='강연', detail={'type': 'author'})
        SignalEvidence.objects.create(signal=s, entry=ContextEntry.objects.get())
        forget = msg(GROUP, '/잊어', reply_to=1, date=DATE)
        forget['message']['message_id'] = 2
        bot.handle_update(forget)
        self.assertFalse(Signal.objects.exists())

    def test_forget_reply_survives_moment_drop_failure(self):
        self.on()
        bot = self.bot()
        bot.handle_update(msg(GROUP, '지울 글', date=DATE))
        forget = msg(GROUP, '/잊어', reply_to=1, date=DATE)
        forget['message']['message_id'] = 2
        with mock.patch('marketing.moments.drop_for_entries', side_effect=RuntimeError('db')):
            bot.handle_update(forget)
        self.assertEqual(self.tg.texts()[-1], '기록에서 지웠어요. 텔레그램 메시지는 직접 지워 주세요.')
        self.assertTrue(ContextEntry.objects.get().forgotten)

    def test_forget_on_draft_card_is_not_an_edit_request(self):
        bot = self.bot({'changes': [{'field': 'subtitle', 'new_value': 'x'}], 'questions': []})
        bot.handle_update(msg(GROUP, '/잊어', reply_to=777))
        self.assertFalse(PendingPatch.objects.exists())
        self.assertEqual(self.tg.texts()[-1], '찾지 못했어요. 예전 대화라면 개발자에게 말씀해 주세요.')

    def test_forget_without_reply_explains(self):
        self.bot().handle_update(msg(GROUP, '/forget'))
        self.assertIn('답장으로 /잊어', self.tg.texts()[-1])

    def test_ctx_admin_commands(self):
        bot = self.bot()
        bot.handle_update(msg(ADMIN, '/ctx on', chat_type='private'))
        self.assertIs(WorkerState.get('context_record'), True)
        bot.handle_update(msg(ADMIN, '/ctx', chat_type='private'))
        self.assertIn('ctx=on', self.tg.texts()[-1])
        self.assertIn('기록 0건', self.tg.texts()[-1])
        bot.handle_update(msg(ADMIN, '/ctx announce', chat_type='private'))
        self.assertTrue(any(c[1] == GROUP and '지우기 전에' in c[2] and '/잊어' in c[2]
                            for c in self.tg.calls if c[0] == 'send'))
        bot.handle_update(msg(ADMIN, '/ctx off', chat_type='private'))
        self.assertIs(WorkerState.get('context_record'), False)

    def test_forget_reaches_imported_history_by_reply_time(self):
        from datetime import datetime, timezone
        ContextEntry.objects.create(key=f'tgx:{GROUP}:500', origin='export', chat_id=GROUP, text='옛 글',
                                    at=datetime.fromtimestamp(DATE, tz=timezone.utc))
        forget = msg(GROUP, '/잊어', reply_to=9)
        forget['message']['reply_to_message']['date'] = DATE
        self.bot().handle_update(forget)
        self.assertEqual(ContextEntry.objects.get().text, '')
        self.assertEqual(self.tg.texts()[-1], '기록에서 지웠어요. 텔레그램 메시지는 직접 지워 주세요.')

    def test_register_command_is_not_recorded(self):
        self.on()
        self.bot().handle_update(msg(GROUP, '/register letmein', date=DATE))
        self.assertFalse(ContextEntry.objects.exists())
