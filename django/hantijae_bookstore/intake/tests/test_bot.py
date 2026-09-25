import json
import os
import tempfile
from datetime import date
from unittest import mock

from django.test import TestCase, override_settings
from PIL import Image

from books.models import Book, Category
from intake import drafts
from intake.bot import Bot, parse_folder_id
from intake.models import BookDraft, IntakeSource, PendingPatch, TelegramChat, WorkerState

WORK = tempfile.mkdtemp()
CONFIG = {'TELEGRAM_INVITE_CODE': 'letmein', 'WORK_DIR': WORK, 'NOTION_DATA_SOURCE_ID': 'ds'}
ADMIN, FAMILY = 100, -200


class FakeTG:
    def __init__(self):
        self.calls, self.next_id = [], 1000

    def _msg(self):
        self.next_id += 1
        return {'message_id': self.next_id}

    def send_message(self, chat_id, text, reply_to=None, buttons=None):
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


def msg(chat_id, text='', reply_to=None, chat_type='group', **extra):
    m = {'message_id': 1, 'chat': {'id': chat_id, 'type': chat_type, 'title': 't'},
         'from': {'first_name': '엄마'}, 'text': text}
    if reply_to:
        m['reply_to_message'] = {'message_id': reply_to}
    m.update(extra)
    return {'update_id': 1, 'message': m}


def cb(chat_id, data):
    return {'update_id': 2, 'callback_query': {'id': 'q', 'data': data, 'from': {'first_name': '아빠'},
                                               'message': {'message_id': 555, 'chat': {'id': chat_id}}}}


@override_settings(INTAKE=CONFIG)
class BotTest(TestCase):
    def setUp(self):
        self.tg = FakeTG()
        cat = Category.objects.create(name='에세이')
        book = Book.objects.create(title='무지개를 변호하다', subtitle='삶과 생각', full_price=22000, page_count=264,
                                   category=cat, published_date=date(2026, 6, 1), is_published=False)
        src = IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='x')
        self.draft = BookDraft.objects.create(source=src, book=book, state=BookDraft.REVIEW, chat_id=FAMILY,
                                              message_id=777, extracted={'_unresolved': [], '_edited': [], '_notes': [],
                                                                         '_source_quality': 0.9})
        TelegramChat.objects.create(chat_id=ADMIN, kind=TelegramChat.ADMIN)
        TelegramChat.objects.create(chat_id=FAMILY, kind=TelegramChat.FAMILY)

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
        self.assertTrue(TelegramChat.objects.filter(chat_id=-9, kind=TelegramChat.FAMILY).exists())

    def test_unregistered_chat_is_ignored(self):
        self.bot().handle_update(msg(-12345, '/status'))
        self.bot().handle_update(cb(-12345, 'pubok:1:1'))
        self.assertEqual([c for c in self.tg.calls if c[0] != 'answer'], [])

    def test_reply_proposes_patch_and_apply_updates_caption(self):
        reply = {'changes': [{'field': 'subtitle', 'new_value': '삶과 싸움'}], 'questions': []}
        self.bot(reply).handle_update(msg(FAMILY, '부제는 삶과 싸움이야', reply_to=777))
        self.assertIn('• 부제: 삶과 생각 → 삶과 싸움', self.tg.texts()[-1])
        patch = PendingPatch.objects.get()
        self.bot().handle_update(cb(FAMILY, f'apply:{patch.id}'))
        self.assertEqual(Book.objects.get().subtitle, '삶과 싸움')
        self.assertTrue(any(c[0] == 'edit' and '삶과 싸움' in c[2] for c in self.tg.calls))
        self.assertEqual(self.tg.calls[-1], ('answer', 'q', '반영했어요'))

    def test_stale_callback_answers_with_message(self):
        self.bot().handle_update(cb(FAMILY, f'img:{self.draft.id}:{self.draft.version + 3}'))
        self.assertIn('다른 분이', self.tg.calls[-1][2])

    def test_publish_is_blocked_in_admin_only_mode(self):
        self.bot().handle_update(cb(FAMILY, f'pubok:{self.draft.id}:{self.draft.version}'))
        self.assertIn('리허설', self.tg.calls[-1][2])
        self.assertFalse(Book.objects.get().is_published)

    def test_publish_in_live_mode_fills_notion(self):
        WorkerState.put('mode', 'live')
        WorkerState.put('notion_write', True)
        notion = mock.Mock()
        with mock.patch('intake.publish.check_book', return_value=[]), \
                mock.patch('intake.bot.fill_notion_row', return_value={'page_id': 'p1', 'filled': ['ISBN'], 'note': ''}) as fill:
            Bot(self.tg, FakeLLM({}), notion=notion, config=CONFIG).handle_update(
                cb(FAMILY, f'pubok:{self.draft.id}:{self.draft.version}'))
        self.assertTrue(Book.objects.get().is_published)
        fill.assert_called_once()
        self.assertEqual(BookDraft.objects.get().notion_page_id, 'p1')

    def test_newbook_collects_files_then_queues(self):
        bot = self.bot()
        bot.handle_update(msg(FAMILY, '/newbook'))
        prompt_id = self.tg.next_id
        src = IntakeSource.objects.get(kind=IntakeSource.TELEGRAM)
        bot.handle_update(msg(FAMILY, '', reply_to=prompt_id,
                              document={'file_id': 'f1', 'file_name': '보도자료_새책.pdf', 'file_size': 1000}))
        self.assertTrue(os.path.exists(os.path.join(src.local_dir, '보도자료_새책.pdf')))
        bot.handle_update(msg(FAMILY, '완료', reply_to=prompt_id))
        self.assertEqual(IntakeSource.objects.get(pk=src.pk).status, IntakeSource.QUEUED)

    def test_admin_link_triggers_ingest(self):
        ops = mock.Mock()
        ops.ingest.return_value = IntakeSource(title='보도자료_새책')
        self.bot(drive_ops=ops).handle_update(
            msg(ADMIN, 'https://drive.google.com/drive/folders/1AbCdEfGhIjK', chat_type='private'))
        ops.ingest.assert_called_once_with('1AbCdEfGhIjK')


class StrictFakeTG(FakeTG):
    """텔레그램처럼 텍스트 메시지에 editMessageCaption을 거절한다."""
    def __init__(self):
        super().__init__()
        self.kinds = {}

    def _msg(self, kind='text'):
        m = super()._msg()
        self.kinds[m['message_id']] = kind
        return m

    def send_message(self, chat_id, text, reply_to=None, buttons=None):
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

    def edit_text(self, chat_id, message_id, text, buttons=None):
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
        TelegramChat.objects.create(chat_id=FAMILY, kind=TelegramChat.FAMILY)
        WorkerState.put('mode', 'live')

    def test_coverless_draft_can_be_fixed_by_photo_reply(self):
        bot = Bot(self.tg, FakeLLM({}), config=CONFIG)
        bot.notify_draft(self.draft)                                   # 표지 없음 → 텍스트 메시지
        draft_msg = BookDraft.objects.get().message_id
        bot.handle_update(msg(FAMILY, '', reply_to=draft_msg, photo=[{'file_id': 'p1'}]))
        self.assertTrue(Book.objects.get().cover_image)
        self.assertIn('앞표지를 이 사진으로 바꿨어요', self.tg.texts())
        self.assertFalse([t for t in self.tg.texts() if '오류' in t])

    def test_reply_to_patch_proposal_starts_a_new_patch_for_the_same_draft(self):
        reply = {'changes': [{'field': 'subtitle', 'new_value': '새 부제'}], 'questions': []}
        bot = Bot(self.tg, FakeLLM(reply), config=CONFIG)
        bot.notify_draft(self.draft)
        bot.handle_update(msg(FAMILY, '부제 바꿔줘', reply_to=BookDraft.objects.get().message_id))
        proposal_id = PendingPatch.objects.get().message_id
        bot.handle_update(msg(FAMILY, '아, 그리고 부제는 새 부제로', reply_to=proposal_id))
        self.assertEqual(PendingPatch.objects.count(), 2)

    def test_reply_to_other_bot_message_gets_guidance(self):
        bot = Bot(self.tg, FakeLLM({}), config=CONFIG)
        sent = self.tg.send_message(FAMILY, '반영했어요')
        bot.handle_update(msg(FAMILY, '고마워', reply_to=sent['message_id']))
        self.assertIn('초안 사진 메시지', self.tg.texts()[-1])
