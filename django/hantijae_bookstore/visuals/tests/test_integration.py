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

    def test_reopening_sent_cards_points_to_existing_album_without_resending(self):
        from visuals.pipeline import enqueue
        job = enqueue(self.draft, -200, 50)
        job.state, job.files = 'sent', ['01.png', '02.png']
        job.receipt = {'images': [70, 71], 'document': 72}
        job.plan = {'missing': ['목차']}
        job.save()
        tg = FakeTG()
        Marketing(tg, FakeLLM({}), FakeHost()).handle_callback(
            'mk:v:' + str(self.draft.pk), -200, {'message': {'message_id': 50, 'text': '글 보기'}}, '운영진')
        memo, body = tg.sent('send')
        self.assertIn('2장', memo['text'])
        self.assertIn('목차', memo['text'])
        self.assertNotIn('만들어 주세요', memo['text'])
        self.assertEqual(memo['reply_to'], 70)
        self.assertIsNone(memo['quote'])
        self.assertEqual(body['text'], '소개')
        self.assertEqual(body['reply_to'], 50)
        self.assertEqual(CardJob.objects.count(), 1)

    def test_unknown_delivery_is_not_presented_as_sent_and_other_chat_receipts_are_not_used(self):
        from visuals.pipeline import enqueue
        job = enqueue(self.draft, -200, 50)
        job.state, job.receipt = 'uncertain', {'images': [70]}
        job.save()
        tg = FakeTG()
        Marketing(tg, FakeLLM({}), FakeHost())._send_draft(self.draft, -200, reply_to=50)
        self.assertIn('전달 결과', tg.sent('send')[0]['text'])
        self.assertNotIn('전달 완료', tg.sent('send')[0]['text'])
        self.assertEqual(CardJob.objects.get().state, 'uncertain')
        job.state, job.chat_id = 'sent', -300
        job.save()
        tg = FakeTG()
        tg.next_id = 2000
        Marketing(tg, FakeLLM({}), FakeHost())._send_draft(self.draft, -200, reply_to=50)
        self.assertEqual(tg.sent('send')[0]['reply_to'], 50)

    def test_changed_copy_does_not_point_to_old_cards(self):
        from visuals.pipeline import enqueue
        job = enqueue(self.draft, -200, 50)
        job.state, job.receipt = 'sent', {'images': [70], 'document': 71}
        job.save()
        self.draft.body = '새로 고친 소개'
        self.draft.save()
        tg = FakeTG()
        Marketing(tg, FakeLLM({}), FakeHost())._send_draft(self.draft, -200, reply_to=50)
        self.assertEqual(tg.sent('send')[0]['reply_to'], 50)
        self.assertEqual(CardJob.objects.count(), 2)

    def test_stopped_or_ineligible_jobs_do_not_promise_automatic_delivery(self):
        from visuals.pipeline import enqueue
        from visuals.presentation import draft_status
        job = enqueue(self.draft, -200, 50)
        WorkerState.put('visuals_heartbeat', (timezone.now() - timedelta(days=2)).isoformat())
        self.assertIn('확인', draft_status(self.draft, -200)[0])
        self.assertNotIn('준비하고 있어요', draft_status(self.draft, -200)[0])
        WorkerState.put('visuals_heartbeat', timezone.now().isoformat())
        self.draft.status = Draft.POSTED
        self.draft.save()
        self.assertIn('중단', draft_status(self.draft, -200)[0])
        self.assertIsNone(draft_status(self.draft, -200)[1])

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

    def test_ops_surfaces_failed_illustration_decision_even_without_art_reservation(self):
        from visuals.pipeline import enqueue
        now = timezone.now()
        WorkerState.put('visuals_heartbeat', now.isoformat())
        job = enqueue(self.draft, -200, 20)
        job.state = 'sent'
        job.error = '일러스트 제외: LLMTransientError'
        job.save()
        row = Row('visuals', '홍보 이미지', '')
        _visuals(_Ctx(now), row)
        self.assertEqual(row.state, 'warn')
