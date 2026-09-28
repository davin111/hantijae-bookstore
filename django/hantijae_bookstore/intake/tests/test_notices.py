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


class PostedEditTest(TestCase):
    """게시 중인 알림은 답장으로 고쳐도 [반영] 전까지 첫 화면이 그대로다."""

    def posted(self, **kw):
        return Notice.objects.create(state=Notice.POSTED, message='예전 문구', link_url='https://old.example/',
                                     link_label='자세히 보기', starts_at=NOW - timedelta(days=1),
                                     ends_at=NOW + timedelta(days=5), **kw)

    def test_reply_to_posted_notice_waits_for_confirmation(self):
        n = self.posted()
        notices.fill_from_text(n, '문구 바꿔 주세요', FakeLLM(DATA), NOW)
        n.refresh_from_db()
        self.assertEqual((n.state, n.message), (Notice.POSTED, '예전 문구'))
        self.assertEqual(n.pending['message'], '『무궁화호를 위하여』 알라딘 북펀드 진행 중')
        self.assertEqual(Notice.objects.active(NOW).first().message, '예전 문구')

    def test_second_reply_builds_on_the_proposal(self):
        n = self.posted()
        notices.fill_from_text(n, '문구 바꿔 주세요', FakeLLM(DATA), NOW)
        llm = RecordingLLM(dict(DATA, end_date='2026-10-15'))
        notices.fill_from_text(n, '마감은 15일로', llm, NOW)
        self.assertIn('무궁화호', llm.last_user)
        self.assertNotIn('예전 문구', llm.last_user)
        n.refresh_from_db()
        self.assertEqual(n.proposal().ends_at, datetime(2026, 10, 16, 0, 0, tzinfo=notices.KST))

    def test_apply_goes_live_and_undo_restores(self):
        n = self.posted()
        notices.fill_from_text(n, '문구 바꿔 주세요', FakeLLM(DATA), NOW)
        n = notices.apply_pending(n.id, NOW)
        self.assertEqual((n.message, n.pending), ('『무궁화호를 위하여』 알라딘 북펀드 진행 중', None))
        self.assertEqual(Notice.objects.active(NOW).first().message, n.message)
        with self.assertRaises(notices.NoticeError):
            notices.apply_pending(n.id, NOW)
        n = notices.undo(n.id, n.previous['at'])
        n.refresh_from_db()
        self.assertEqual((n.message, n.link_url, n.previous), ('예전 문구', 'https://old.example/', None))
        self.assertEqual(n.ends_at, NOW + timedelta(days=5))
        with self.assertRaises(notices.NoticeError):
            notices.undo(n.id, 0)

    def test_old_undo_button_cannot_revert_a_newer_change(self):
        n = self.posted()
        notices.fill_from_text(n, '첫 수정', FakeLLM(DATA), NOW)
        first = notices.apply_pending(n.id, NOW).previous['at']
        notices.fill_from_text(n, '두 번째 수정', FakeLLM(dict(DATA, message='두 번째 문구')), NOW)
        notices.apply_pending(n.id, NOW + timedelta(seconds=5))
        with self.assertRaises(notices.NoticeError):
            notices.undo(n.id, first)
        n.refresh_from_db()
        self.assertEqual(n.message, '두 번째 문구')

    def test_discard_keeps_live_notice(self):
        n = self.posted()
        notices.fill_from_text(n, '문구 바꿔 주세요', FakeLLM(DATA), NOW)
        n = notices.discard_pending(n.id)
        n.refresh_from_db()
        self.assertEqual((n.message, n.pending), ('예전 문구', None))
        with self.assertRaises(notices.NoticeError):
            notices.discard_pending(n.id)

    def test_taking_down_drops_the_proposal(self):
        n = self.posted()
        notices.fill_from_text(n, '문구 바꿔 주세요', FakeLLM(DATA), NOW)
        notices.set_state(n.id, Notice.REMOVED)
        n.refresh_from_db()
        self.assertIsNone(n.pending)
        with self.assertRaises(notices.NoticeError):
            notices.apply_pending(n.id, NOW)

    def test_draft_edit_still_applies_in_place(self):
        n = Notice.objects.create(state=Notice.DRAFT, message='미리보기 문구')
        notices.fill_from_text(n, '문구 바꿔 주세요', FakeLLM(DATA), NOW)
        n.refresh_from_db()
        self.assertEqual((n.message, n.pending), ('『무궁화호를 위하여』 알라딘 북펀드 진행 중', None))

    def test_wording_only_edit_keeps_the_live_period(self):
        n = self.posted()
        n.link_url, n.ends_at = DATA['link_url'], datetime(2026, 10, 12, 0, 0, tzinfo=notices.KST)
        n.link_label = '함께하기'
        n.save()
        notices.fill_from_text(n, '문구만 바꿔 주세요', FakeLLM(DATA), NOW)
        n.refresh_from_db()
        self.assertEqual(n.proposal().starts_at, NOW - timedelta(days=1))
        text = messages.notice_card(n)
        self.assertIn('지금 첫 화면:\n예전 문구 · 함께하기 →\n더 고칠', text)   # 기간·연결은 그대로라 안 나옴

    def test_future_start_date_is_kept_in_proposal(self):
        n = self.posted()
        notices.fill_from_text(n, '10월 1일부터', FakeLLM(dict(DATA, start_date='2026-10-01')), NOW)
        n.refresh_from_db()
        self.assertEqual(n.proposal().starts_at, datetime(2026, 10, 1, 0, 0, tzinfo=notices.KST))

    def test_proposal_card_shows_new_values_and_what_is_live_now(self):
        n = self.posted()
        notices.fill_from_text(n, '문구 바꿔 주세요', FakeLLM(DATA), NOW)
        text = messages.notice_card(n)
        self.assertIn('이렇게 바꿀까요?', text)
        self.assertIn('『무궁화호를 위하여』 알라딘 북펀드 진행 중 · 함께하기 →', text)
        self.assertIn('지금 첫 화면', text)
        self.assertIn('예전 문구 · 자세히 보기 →', text)
        buttons = [b['callback_data'] for b in messages.notice_buttons(n)['inline_keyboard'][0]]
        self.assertEqual(buttons, [f'ntok:{n.id}', f'ntno:{n.id}'])


@override_settings(INTAKE=CONFIG)
class PostedEditBotTest(TestCase):
    def setUp(self):
        self.tg = TG()
        TelegramChat.objects.create(chat_id=ADMIN, kind=TelegramChat.ADMIN)
        TelegramChat.objects.create(chat_id=GROUP, kind=TelegramChat.REVIEWERS)
        self.n = Notice.objects.create(state=Notice.POSTED, message='예전 문구', chat_id=GROUP, message_id=1500,
                                       ends_at=timezone.now() + timedelta(days=5))
        self.bot = Bot(self.tg, FakeLLM(DATA), config=CONFIG)

    def test_reply_sends_proposal_card_without_touching_the_site(self):
        self.bot.handle_update(msg(GROUP, '문구 바꿔 주세요', reply_to=1500))
        send = [c for c in self.tg.calls if c[0] == 'send'][-1]
        self.assertIn('이렇게 바꿀까요?', send[2])
        self.assertEqual(send[3]['inline_keyboard'][0][0]['callback_data'], f'ntok:{self.n.id}')
        self.n.refresh_from_db()
        self.assertEqual(self.n.message, '예전 문구')
        self.assertEqual(self.n.message_id, 1001)   # 다음 답장은 새 카드에

    def test_confirm_then_undo(self):
        self.bot.handle_update(msg(GROUP, '문구 바꿔 주세요', reply_to=1500))
        self.bot.handle_update(cb(GROUP, f'ntok:{self.n.id}'))
        self.assertIn(('answer', 'q', '반영했어요'), self.tg.calls)
        self.n.refresh_from_db()
        self.assertEqual(self.n.message, '『무궁화호를 위하여』 알라딘 북펀드 진행 중')
        self.assertTrue(any(c[0] == 'edit_text' and '첫 화면에 떠 있는 알림' in c[2] for c in self.tg.calls))
        done = [c for c in self.tg.calls if c[0] == 'send' and '첫 화면 알림을 바꿨어요' in c[2]][-1]
        undo = done[3]['inline_keyboard'][0][0]['callback_data']
        self.assertEqual(undo, f"ntundo:{self.n.id}:{self.n.previous['at']}")
        self.bot.handle_update(cb(GROUP, undo))
        self.assertIn(('answer', 'q', '되돌렸어요'), self.tg.calls)
        self.n.refresh_from_db()
        self.assertEqual(self.n.message, '예전 문구')
        self.bot.handle_update(cb(GROUP, undo))
        self.assertIn(('answer', 'q', '이미 되돌렸어요.'), self.tg.calls)

    def test_cancel_keeps_live_notice(self):
        self.bot.handle_update(msg(GROUP, '문구 바꿔 주세요', reply_to=1500))
        self.bot.handle_update(cb(GROUP, f'ntno:{self.n.id}'))
        self.assertIn(('answer', 'q', '취소했어요'), self.tg.calls)
        self.n.refresh_from_db()
        self.assertEqual((self.n.message, self.n.pending), ('예전 문구', None))
        edit = [c for c in self.tg.calls if c[0] == 'edit_text'][-1]
        self.assertIn('첫 화면에 떠 있는 알림', edit[2])
        self.assertEqual(edit[3]['inline_keyboard'][0][0]['callback_data'], f'ntoff:{self.n.id}')
