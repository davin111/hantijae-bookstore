from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from intake import messages, notices
from intake.bot import Bot
from intake.llm import LLMError
from intake.models import TelegramChat
from intake.tests.test_bot import ADMIN, CONFIG, GROUP, FakeLLM, FakeTG, cb, msg
from web.models import Notice

NOW = datetime(2026, 9, 28, 3, 0, tzinfo=dt_timezone.utc)   # 한국 시간 9월 28일 12시
DATA = {'message': ' 『무궁화호를 위하여』 알라딘 북펀드 진행 중 ', 'link_url': 'https://www.aladin.co.kr/m/bookfund/view.aspx?pid=1',
        'link_label': '함께하기', 'start_date': None, 'end_date': '2026-10-11'}


class TG(FakeTG):
    def edit_text(self, chat_id, message_id, text, buttons=None):
        self.calls.append(('edit_text', chat_id, text, buttons))


class RecordingLLM(FakeLLM):
    def complete(self, system, user, attachments=()):
        self.last_system, self.last_user = system, user
        return super().complete(system, user, attachments)


class FailingLLM:
    def complete(self, system, user, attachments=()):
        raise LLMError('sidecar down')


class ApplyFieldsTest(TestCase):
    def notice(self, **kw):
        return Notice.objects.create(state=kw.pop('state', Notice.ASKING), **kw)

    def test_end_date_is_inclusive_korean_day_and_state_becomes_draft(self):
        n = self.notice()
        self.assertEqual(notices.apply_fields(n, DATA, NOW), [])
        n.refresh_from_db()
        self.assertEqual(n.state, Notice.DRAFT)
        self.assertEqual(n.message, '『무궁화호를 위하여』 알라딘 북펀드 진행 중')
        self.assertEqual(n.starts_at, NOW)
        self.assertEqual(n.ends_at, datetime(2026, 10, 12, 0, 0, tzinfo=notices.KST))
        self.assertEqual(n.link_label, '함께하기')

    def test_defaults_to_thirty_days_and_label(self):
        n = self.notice()
        notices.apply_fields(n, {'message': '북토크 소식'}, NOW)
        self.assertEqual(n.ends_at, NOW + timedelta(days=30))
        self.assertEqual(n.link_label, '자세히 보기')
        self.assertEqual(n.link_url, '')

    def test_future_start_date(self):
        n = self.notice()
        notices.apply_fields(n, dict(DATA, start_date='2026-10-01'), NOW)
        self.assertEqual(n.starts_at, datetime(2026, 10, 1, 0, 0, tzinfo=notices.KST))

    def test_apply_fields_ignores_bad_dates(self):
        n = self.notice()
        warnings = notices.apply_fields(n, dict(DATA, end_date='10/2'), NOW)
        self.assertIn('날짜를 알아보지 못해 기본 기간(오늘부터 30일)으로 두었어요.', warnings)
        self.assertEqual(n.ends_at, NOW + timedelta(days=30))
        warnings = notices.apply_fields(n, dict(DATA, start_date='2026-10-10', end_date='2026-10-01'), NOW)
        self.assertIn('끝나는 날이 시작보다 앞서 기본 기간(30일)으로 두었어요.', warnings)
        warnings = notices.apply_fields(n, dict(DATA, end_date='2026-09-01'), NOW)
        self.assertIn('끝나는 날이 시작보다 앞서 기본 기간(30일)으로 두었어요.', warnings)

    def test_bad_url_and_long_message_warn(self):
        n = self.notice()
        warnings = notices.apply_fields(n, dict(DATA, link_url='www.aladin.co.kr', message='가' * 61), NOW)
        self.assertEqual(n.link_url, '')
        self.assertEqual(len(warnings), 2)

    def test_overlong_url_is_dropped_instead_of_failing_save(self):
        n = self.notice()
        warnings = notices.apply_fields(n, dict(DATA, link_url='https://example.com/' + 'a' * 600), NOW)
        self.assertEqual(n.link_url, '')
        self.assertIn('연결 주소가 너무 길어 빼 두었어요.', warnings)

    def test_empty_message_raises(self):
        with self.assertRaises(notices.NoticeError):
            notices.apply_fields(self.notice(), {'message': '  '}, NOW)

    def test_editing_posted_keeps_posted(self):
        n = self.notice(state=Notice.POSTED, message='예전')
        notices.apply_fields(n, DATA, NOW)
        self.assertEqual(n.state, Notice.POSTED)

    def test_set_state_transitions(self):
        n = self.notice(state=Notice.DRAFT, message='m')
        self.assertEqual(notices.set_state(n.id, Notice.POSTED).state, Notice.POSTED)
        with self.assertRaises(notices.NoticeError):
            notices.set_state(n.id, Notice.POSTED)
        self.assertEqual(notices.set_state(n.id, Notice.REMOVED).state, Notice.REMOVED)
        with self.assertRaises(notices.NoticeError):
            notices.set_state(999999, Notice.POSTED)

    def test_card_text(self):
        n = self.notice()
        notices.apply_fields(n, DATA, NOW)
        text = messages.notice_card(n)
        self.assertIn('📣 알림 띠 미리보기', text)
        self.assertIn('『무궁화호를 위하여』 알라딘 북펀드 진행 중 · 함께하기 →', text)
        self.assertIn('기간: 9월 28일 ~ 10월 11일', text)
        self.assertIn('고칠 내용은 이 메시지에 답장으로 적어 주세요.', text)


@override_settings(INTAKE=CONFIG)
class NoticeBotTest(TestCase):
    def setUp(self):
        self.tg = TG()
        TelegramChat.objects.create(chat_id=ADMIN, kind=TelegramChat.ADMIN)
        TelegramChat.objects.create(chat_id=GROUP, kind=TelegramChat.REVIEWERS)

    def bot(self, llm=None):
        return Bot(self.tg, llm or RecordingLLM(DATA), config=CONFIG)

    def test_command_prompts_and_reply_builds_draft_card(self):
        bot = self.bot()
        bot.handle_update(msg(GROUP, '/notice'))
        self.assertEqual(self.tg.texts()[-1], messages.NOTICE_PROMPT)
        n = Notice.objects.get()
        self.assertEqual((n.state, n.message_id, n.created_by), (Notice.ASKING, 1001, '검수자A'))
        bot.handle_update(msg(GROUP, '무궁화호 북펀드 10월 11일까지 https://…', reply_to=1001))
        n.refresh_from_db()
        self.assertEqual(n.state, Notice.DRAFT)
        send = [c for c in self.tg.calls if c[0] == 'send'][-1]
        self.assertIn('📣 알림 띠 미리보기', send[2])
        self.assertEqual(send[3]['inline_keyboard'][0][0]['callback_data'], f'ntpub:{n.id}')
        self.assertEqual(n.message_id, 1002)

    def test_reply_to_card_revises_with_current_values(self):
        llm = RecordingLLM(DATA)
        bot = self.bot(llm)
        bot.handle_update(msg(GROUP, '/notice'))
        bot.handle_update(msg(GROUP, '첫 내용', reply_to=1001))
        bot.handle_update(msg(GROUP, '마감을 10월 15일로 바꿔 주세요', reply_to=1002))
        self.assertIn('현재 알림', llm.last_user)
        self.assertIn('2026', llm.last_system)   # 오늘 날짜가 프롬프트에 들어감

    def test_publish_take_down_and_stale_buttons(self):
        n = Notice.objects.create(state=Notice.DRAFT, message='m', chat_id=GROUP, message_id=1500,
                                  ends_at=timezone.now() + timedelta(days=3))
        bot = self.bot()
        bot.handle_update(cb(GROUP, f'ntpub:{n.id}'))
        n.refresh_from_db()
        self.assertEqual(n.state, Notice.POSTED)
        self.assertIn(('answer', 'q', '게시했어요'), self.tg.calls)
        self.assertTrue(any(c[0] == 'edit_text' and '첫 화면에 떠 있는 알림' in c[2] for c in self.tg.calls))
        self.assertTrue(any('✅ 첫 화면에 띄웠어요' in t for t in self.tg.texts()))
        bot.handle_update(cb(GROUP, f'ntpub:{n.id}'))
        self.assertIn(('answer', 'q', '이미 처리된 알림이에요.'), self.tg.calls)
        bot.handle_update(cb(GROUP, f'ntoff:{n.id}'))
        n.refresh_from_db()
        self.assertEqual(n.state, Notice.REMOVED)
        self.assertIn(('answer', 'q', '내렸어요'), self.tg.calls)

    def test_active_notice_shown_before_prompt(self):
        Notice.objects.create(message='지금 떠 있는 것', ends_at=timezone.now() + timedelta(days=1))
        self.bot().handle_update(msg(GROUP, '/notice'))
        texts = self.tg.texts()
        self.assertIn('📣 첫 화면에 떠 있는 알림', texts[0])
        self.assertEqual(texts[1], messages.NOTICE_PROMPT)

    def test_llm_failure_tells_reviewers_and_admin(self):
        bot = self.bot(FailingLLM())
        bot.handle_update(msg(GROUP, '/notice'))
        bot.handle_update(msg(GROUP, '북펀드', reply_to=1001))
        self.assertIn('지금은 알림을 만들지 못했어요. 잠시 후 다시 답장해 주세요.', self.tg.texts())
        self.assertTrue(any(c[1] == ADMIN and '알림 띠 요청 처리 실패' in c[2] for c in self.tg.calls if c[0] == 'send'))

    def test_admin_chat_can_use_notice_and_unregistered_is_ignored(self):
        self.bot().handle_update(msg(ADMIN, '/notice', chat_type='private'))
        self.assertEqual(self.tg.texts()[-1], messages.NOTICE_PROMPT)
        before = len(self.tg.calls)
        self.bot().handle_update(msg(-999, '/notice'))
        self.assertEqual(len(self.tg.calls), before)
