from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from intake.models import TelegramChat, WorkerState
from marketing.bot import Marketing
from marketing.models import Draft, Proposal
from marketing.tests.fakes import FakeLLM, FakeTG, make_book
from marketing.tests.test_bot import FakeHost
from ops.health import Row, _Ctx, _visuals
from visuals.models import CardJob


class IntegrationTest(TestCase):
    def setUp(self):
        WorkerState.put('visuals_mode', 'live')
        WorkerState.put('marketing_mode', 'live')
        TelegramChat.objects.create(chat_id=-200, kind='reviewers')
        p = Proposal.objects.create(book=make_book(), kind='kit', headline='신간')
        self.draft = Draft.objects.create(proposal=p, channel='instagram', body='소개',
                                          extra={'cards': [{'show': '글자 카드', 'text': '소개'}]})

    def test_existing_text_and_buttons_send_before_image_job(self):
        tg, llm = FakeTG(), FakeLLM({})
        Marketing(tg, llm, FakeHost())._send_draft(self.draft, -200)
        self.assertEqual(CardJob.objects.count(), 1)
        self.assertTrue(tg.calls[-1]['buttons'])
        self.assertFalse(llm.calls)
        self.assertEqual(CardJob.objects.get().reply_to, tg.next_id)

    def test_queue_failure_never_turns_successful_text_send_into_a_failure(self):
        tg = FakeTG()
        with mock.patch('visuals.pipeline.enqueue', side_effect=RuntimeError('DB issue')):
            with self.assertLogs('intake', level='ERROR'):
                Marketing(tg, FakeLLM({}), FakeHost())._send_draft(self.draft, -200)
        self.assertTrue(tg.calls[-1]['buttons'])

    def test_ops_reports_stale_worker_and_actual_success_separately(self):
        now = timezone.now()
        WorkerState.put('visuals_heartbeat', (now - timedelta(hours=1)).isoformat())
        row = Row('visuals', '홍보 이미지', '')
        _visuals(_Ctx(now), row)
        self.assertEqual(row.state, 'warn')
        self.assertIn('0건', row.result)
        WorkerState.put('visuals_heartbeat', now.isoformat())
        row = Row('visuals', '홍보 이미지', '')
        _visuals(_Ctx(now), row)
        self.assertEqual(row.state, 'calm')

    def test_even_error_recording_failure_does_not_break_text_delivery(self):
        tg = FakeTG()
        with mock.patch('visuals.pipeline.enqueue', side_effect=RuntimeError('DB down')), \
                mock.patch('visuals.pipeline.WorkerState.put', side_effect=RuntimeError('DB down')):
            with self.assertLogs('intake', level='ERROR'):
                Marketing(tg, FakeLLM({}), FakeHost())._send_draft(self.draft, -200)
        self.assertTrue(tg.calls[-1]['buttons'])
