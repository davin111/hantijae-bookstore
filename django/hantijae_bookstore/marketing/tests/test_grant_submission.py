"""신청 의사와 완료를 구분하고, 지난 버튼/전송 재시도가 완료를 잃지 않는지 검증한다."""
from datetime import date, datetime, timedelta
from unittest import mock

from django.test import TestCase

from intake.bot import Bot
from intake.models import TelegramChat
from marketing import grants, messages
from marketing.bot import Marketing
from marketing.models import GrantCall
from marketing.tests.fakes import FakeLLM, FakeTG, make_call
from marketing.tests.test_bot import GROUP, FakeHost, cbq
from marketing.timeutil import KST

NOW = datetime(2026, 10, 17, 18, 0, tzinfo=KST)
DECIDED = datetime(2026, 10, 1, 13, 0, tzinfo=KST)


class GrantSubmissionTest(TestCase):
    def setUp(self):
        self.tg = FakeTG()
        self.marketing = Marketing(self.tg, FakeLLM({}), FakeHost())
        self.call = make_call(state=GrantCall.APPLYING, chat_id=GROUP, message_id=555,
                              decided_by='운영진A', decided_at=DECIDED)

    def click(self, action='gs', chat=GROUP, message=555, actor='운영진C'):
        with mock.patch('marketing.bot.timezone.now', return_value=NOW):
            return self.marketing.handle_callback(f'mk:{action}:{self.call.id}', chat, cbq(message), actor)

    def test_completion_button_records_after_deadline_without_inventing_submission_date(self):
        self.click()
        self.call.refresh_from_db()
        self.assertEqual(self.call.state, 'submitted')
        self.assertIsNone(self.call.submitted_on)
        self.assertEqual((self.call.submitted_at, self.call.submitted_by), (NOW, '운영진C'))
        self.assertEqual((self.call.decided_by, self.call.decided_at), ('운영진A', DECIDED))
        self.assertEqual(self.call.submission_source, {'chat_id': GROUP, 'message_id': 555})
        edit = self.tg.sent('edit')[0]
        self.assertEqual((edit['chat'], edit['message_id']), (GROUP, 555))
        self.assertIn('신청 완료', edit['text'])
        self.assertNotIn('신청하기로', edit['text'])
        self.assertNotIn('10월 17일', edit['text'])
        self.assertEqual(edit['buttons'], {'inline_keyboard': []})
        self.assertEqual(self.tg.sent('send'), [])

    def test_applying_card_offers_completion_and_other_calls_keep_their_buttons(self):
        other = make_call(no='2168', state=GrantCall.ANNOUNCED, chat_id=GROUP, message_id=555)
        rows = messages.grant_buttons([self.call, other])['inline_keyboard']
        self.assertIn(f'mk:gs:{self.call.id}', [b['callback_data'] for b in rows[0]])
        self.click()
        rows = messages.grant_buttons(grants.card_calls(GROUP, 555))['inline_keyboard']
        self.assertEqual(len(rows), 1)
        self.assertEqual([b['callback_data'] for b in rows[0]], [f'mk:ga:{other.id}', f'mk:gp:{other.id}'])
        other.refresh_from_db()
        self.assertEqual(other.state, GrantCall.ANNOUNCED)

    def test_completion_is_absent_from_briefing_and_deadline_reminder(self):
        self.click()
        self.call.refresh_from_db()
        self.assertEqual(self.call.state, 'submitted')
        self.assertEqual(grants.open_calls(date(2026, 10, 10)), [])
        self.assertEqual(grants.due_reminders(date(2026, 10, 10)), [])
        self.assertEqual(messages.grant_briefing_lines([self.call]), [])
        self.assertIn('신청 완료', grants.status_text(date(2026, 10, 17)))

    def test_old_buttons_and_repeated_completion_preserve_original_completion(self):
        self.click()
        self.call.refresh_from_db()
        self.assertEqual(self.call.state, 'submitted')
        original = (self.call.submitted_at, self.call.submitted_by, self.call.submission_source)
        # 마감 전에도 옛 신청/넘김 버튼은 완료를 되돌리면 안 된다.
        for applying in (True, False):
            grants.decide(self.call.id, applying, '다른 사람', DECIDED + timedelta(days=1))
        self.click(actor='다른 사람')
        self.call.refresh_from_db()
        self.assertEqual(self.call.state, 'submitted')
        self.assertEqual((self.call.submitted_at, self.call.submitted_by, self.call.submission_source), original)

    def test_unrelated_chat_or_card_cannot_change_submission(self):
        for chat, message in [(GROUP - 1, 555), (GROUP, 556)]:
            self.click(chat=chat, message=message)
        self.call.refresh_from_db()
        self.assertEqual(self.call.state, GrantCall.APPLYING)
        self.assertEqual(self.tg.calls, [])

    def test_edit_retry_keeps_truth_and_redraws_same_card_without_new_message(self):
        with mock.patch.object(self.tg, 'edit_text', side_effect=RuntimeError('transport unavailable')):
            with self.assertRaises(RuntimeError):
                self.click()
        self.call.refresh_from_db()
        self.assertEqual(self.call.state, 'submitted')
        self.click()
        self.assertEqual([x['message_id'] for x in self.tg.sent('edit')], [555])
        self.assertEqual(self.tg.sent('send'), [])

    def test_historical_report_keeps_application_date_and_report_date_separate(self):
        # 운영 DB 정정과 같은 경로. 기록 시각을 실제 신청일로 쓰지 않는다.
        result, _ = grants.submit(self.call.id, '운영진A', NOW, submitted_on=date(2026, 10, 8),
                                  source={'chat_id': GROUP, 'message_id': 582, 'reported_on': '2026-10-10'})
        self.assertEqual(result.state, 'submitted')
        self.call.refresh_from_db()
        self.assertEqual(self.call.submitted_on, date(2026, 10, 8))
        self.assertEqual(self.call.submitted_at, NOW)
        text = messages.grant_card_text([self.call])
        self.assertIn('10월 8일 신청', text)
        self.assertIn('10월 10일 보고', text)
        self.assertNotIn('선정', text)
        self.assertNotIn('신청하기로', text)

    def test_unannounced_or_skipped_call_cannot_be_completed(self):
        for state in (GrantCall.READY, GrantCall.ANNOUNCED, GrantCall.PASSED, GrantCall.OLD):
            GrantCall.objects.filter(pk=self.call.pk).update(state=state)
            self.click()
            self.call.refresh_from_db()
            self.assertEqual(self.call.state, state)
        self.assertEqual(self.tg.calls, [])

    def test_real_bot_callback_routes_registered_room_to_completion(self):
        TelegramChat.objects.create(chat_id=GROUP, kind=TelegramChat.REVIEWERS)
        bot = Bot(self.tg, FakeLLM({}), config={})
        query = {'id': 'callback-1', 'data': f'mk:gs:{self.call.id}',
                 'from': {'id': 123, 'first_name': '운영진C'},
                 'message': {'message_id': 555, 'chat': {'id': GROUP, 'type': 'group'}}}
        bot.on_callback(query)
        self.call.refresh_from_db()
        self.assertEqual(self.call.state, 'submitted')
        self.assertIn('신청 완료', self.tg.sent('answer')[0]['text'])
        self.assertEqual([x['message_id'] for x in self.tg.sent('edit')], [555])
