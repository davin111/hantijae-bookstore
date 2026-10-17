import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from intake.models import TelegramChat, WorkerState
from marketing.models import Draft, DraftMessage, Proposal
from marketing.tests.fakes import FakeLLM, make_book
from visuals.models import CardJob
from visuals.pipeline import enqueue, eligible, recover, run_once, reserve_illustration
from visuals.delivery import deliver


class JobsTest(TestCase):
    def setUp(self):
        clock = mock.patch('django.utils.timezone.now', return_value=timezone.now().replace(hour=4))
        clock.start()
        self.addCleanup(clock.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = override_settings(VISUALS_ROOT=self.tmp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        WorkerState.put('visuals_mode', 'live')
        WorkerState.put('marketing_mode', 'live')
        TelegramChat.objects.create(kind='reviewers', chat_id=-200)
        TelegramChat.objects.create(kind='admin', chat_id=100)
        self.book = make_book()
        self.proposal = Proposal.objects.create(book=self.book, kind='kit', headline='책 소식')
        self.draft = Draft.objects.create(proposal=self.proposal, channel='instagram', title='책 소식', body='책 소개',
                                          extra={'cards': [{'show': '글자만 적은 카드', 'text': '책 소개'}]})

    def test_duplicate_requests_queue_once_and_changed_content_has_a_new_job(self):
        first = enqueue(self.draft, -200, 50)
        self.assertEqual(enqueue(self.draft, -200, 51).pk, first.pk)
        self.draft.body = '고친 책 소개'
        self.draft.save()
        second = enqueue(self.draft, -200, 52)
        self.assertNotEqual(first.pk, second.pk)
        self.assertFalse(eligible(first, timezone.now()))

    def test_off_unauthorized_chat_and_posted_draft_do_not_queue(self):
        self.assertIsNone(enqueue(self.draft, 999, 50))
        WorkerState.put('visuals_mode', 'off')
        self.assertIsNone(enqueue(self.draft, -200, 50))
        WorkerState.put('visuals_mode', 'live')
        self.draft.status = Draft.POSTED
        self.draft.save()
        self.assertIsNone(enqueue(self.draft, -200, 50))

    def test_switch_to_admin_only_blocks_queued_review_room_delivery(self):
        job = enqueue(self.draft, -200, 50)
        WorkerState.put('marketing_mode', 'admin_only')
        self.assertFalse(eligible(job, timezone.now()))

    def test_new_version_and_sensitive_signal_cancel_old_job(self):
        job = enqueue(self.draft, -200, 50)
        Draft.objects.create(proposal=self.proposal, channel='instagram', body='새판', version=2)
        self.assertFalse(eligible(job, timezone.now()))

    def test_worker_builds_and_preserves_zip_even_with_illustration_rejected(self):
        job = enqueue(self.draft, -200, 50)
        now = timezone.now().replace(hour=4)  # 13 KST
        tg = mock.Mock()
        tg.call.side_effect = [{'message_id': 2001}, {'message_id': 2002}]
        result = run_once(FakeLLM({'needed': False}), tg, now=now)
        result.refresh_from_db()
        self.assertEqual(result.state, 'sent')
        self.assertEqual(result.pk, job.pk)
        self.assertEqual(DraftMessage.objects.filter(draft=self.draft).count(), 2)
        self.assertTrue((Path(self.tmp.name) / str(job.pk) / 'originals.zip').exists())

    def test_network_failure_during_send_is_uncertain_and_not_retried(self):
        job = enqueue(self.draft, -200, 50)
        tg = mock.Mock()
        tg.call.side_effect = RuntimeError('network timeout')
        run_once(FakeLLM({}), tg, now=timezone.now().replace(hour=4))
        job.refresh_from_db()
        self.assertEqual(job.state, 'uncertain')
        run_once(FakeLLM({}), tg, now=timezone.now().replace(hour=4))
        self.assertEqual(tg.call.call_count, 1)

    def test_partial_delivery_retains_album_receipt(self):
        job = enqueue(self.draft, -200, 50)
        tg = mock.Mock()
        tg.call.side_effect = [{'message_id': 2001}, RuntimeError('ZIP timeout')]
        run_once(FakeLLM({}), tg, now=timezone.now().replace(hour=4))
        job.refresh_from_db()
        self.assertEqual(job.state, 'uncertain')
        self.assertEqual(job.receipt['images'], [2001])
        self.assertEqual(DraftMessage.objects.filter(draft=self.draft).count(), 1)

    def test_interrupted_send_is_not_retried_but_build_can_be_recovered(self):
        job = enqueue(self.draft, -200, 50)
        ago = timezone.now() - timedelta(minutes=20)
        CardJob.objects.filter(pk=job.pk).update(state='sending', started_at=ago)
        recover(timezone.now())
        job.refresh_from_db()
        self.assertEqual(job.state, 'uncertain')
        CardJob.objects.filter(pk=job.pk).update(state='building', attempts=1, started_at=ago)
        recover(timezone.now())
        job.refresh_from_db()
        self.assertEqual(job.state, 'queued')

    def test_cancellation_during_build_prevents_any_telegram_send(self):
        job = enqueue(self.draft, -200, 50)
        from visuals import pipeline
        real_build = pipeline.build
        def changed(*args, **kwargs):
            result = real_build(*args, **kwargs)
            Draft.objects.filter(pk=self.draft.pk).update(status=Draft.SKIPPED)
            return result
        tg = mock.Mock()
        with mock.patch('visuals.pipeline.build', side_effect=changed):
            run_once(FakeLLM({}), tg, now=timezone.now().replace(hour=4))
        job.refresh_from_db()
        self.assertEqual(job.state, 'cancelled')
        tg.call.assert_not_called()

    def test_deliver_cannot_send_an_already_sent_job_again(self):
        job = enqueue(self.draft, -200, 50)
        tg = mock.Mock()
        tg.call.side_effect = [{'message_id': 2001}, {'message_id': 2002}]
        run_once(FakeLLM({}), tg, now=timezone.now().replace(hour=4))
        job.refresh_from_db()
        deliver(job, tg, lambda: True)
        self.assertEqual(tg.call.call_count, 2)

    def test_same_book_is_not_given_another_illustration_within_30_days(self):
        first = enqueue(self.draft, -200, 50)
        self.assertTrue(reserve_illustration(first, timezone.now()))
        second = enqueue(self.draft, 100, 51)
        self.assertFalse(reserve_illustration(second, timezone.now()))

    def test_cover_change_invalidates_queued_cards(self):
        job = enqueue(self.draft, -200, 50)
        type(self.book).objects.filter(pk=self.book.pk).update(cover_image='new-cover.jpg')
        self.assertFalse(eligible(job, timezone.now()))

    def test_cancelled_nested_event_promoted_sensitive_and_hidden_book_block(self):
        from marketing.models import Signal
        s = Signal.objects.create(kind='moment', key='event', title='행사', relevant=True)
        self.proposal.signal = s
        self.proposal.save()
        job = enqueue(self.draft, -200, 50)
        for detail, sensitive in [({'event': {'status': 'cancelled'}}, False),
                                  ({'promoted': True}, False), ({}, True)]:
            Signal.objects.filter(pk=s.pk).update(detail=detail, sensitive=sensitive)
            self.assertFalse(eligible(job, timezone.now()))
        Signal.objects.filter(pk=s.pk).update(detail={}, sensitive=False)
        type(self.book).objects.filter(pk=self.book.pk).update(visible=False)
        self.assertFalse(eligible(job, timezone.now()))

    def test_approved_source_revocation_and_replacement_block_ready_job(self):
        from visuals.models import ApprovedImage
        from visuals.pipeline import build
        folder = Path(self.tmp.name) / 'sources'
        folder.mkdir()
        path = folder / 'toc.png'
        Image.new('RGB', (600, 900), 'white').save(path)
        asset = ApprovedImage.objects.create(book=self.book, kind='toc', path='sources/toc.png', label='목차', source='승인된 원본')
        self.draft.extra = {'cards': [{'show': '목차', 'text': '차례'}]}
        self.draft.save()
        job = enqueue(self.draft, -200, 50)
        build(job, FakeLLM({}), timezone.now())
        self.assertTrue(eligible(job, timezone.now()))
        Image.new('RGB', (600, 900), 'red').save(path)
        self.assertFalse(eligible(job, timezone.now()))
        asset.active = False
        asset.save()
        self.assertFalse(eligible(job, timezone.now()))

    def test_quiet_hours_defer_then_resume_only_remaining_zip(self):
        from visuals.pipeline import build
        from marketing.timeutil import KST
        job = enqueue(self.draft, -200, 50)
        build(job, FakeLLM({}), timezone.now())
        quiet = timezone.now().astimezone(KST).replace(hour=21)
        daylight = quiet.replace(hour=10)
        tg = mock.Mock()
        with mock.patch('visuals.delivery.timezone.now', return_value=quiet):
            deliver(job, tg, lambda: True)
        job.refresh_from_db()
        self.assertEqual(job.state, 'ready')
        tg.call.assert_not_called()
        clock = mock.Mock(return_value=daylight)
        def sent_photo(*args, **kwargs):
            clock.return_value = quiet
            return {'message_id': 2001}
        tg.call.side_effect = sent_photo
        with mock.patch('visuals.delivery.timezone.now', clock):
            deliver(job, tg, lambda: True)
        job.refresh_from_db()
        self.assertEqual(job.state, 'ready')
        self.assertEqual(job.receipt['images'], [2001])
        tg.call.side_effect = None
        tg.call.return_value = {'message_id': 2002}
        with mock.patch('visuals.delivery.timezone.now', return_value=daylight):
            deliver(job, tg, lambda: True)
        self.assertEqual([c.args[0] for c in tg.call.call_args_list], ['sendPhoto', 'sendDocument'])

    def test_unused_fifth_theme_never_calls_ai_or_consumes_budget(self):
        from visuals.pipeline import build
        self.draft.extra = {'cards': [{'show': '글 카드', 'text': '책 소개'}] * 4 + [{'show': '가을 산 풍경', 'text': '가을 소식'}]}
        self.draft.save()
        job = enqueue(self.draft, -200, 50)
        llm = mock.Mock()
        build(job, llm, timezone.now())
        llm.complete.assert_not_called()
        self.assertIsNone(job.illustration_at)
        self.assertIsNone(job.plan['illustration'])

    def test_album_sends_two_photos_and_original_zip_once(self):
        self.draft.extra['cards'] *= 2
        self.draft.save()
        job = enqueue(self.draft, -200, 50)
        tg = mock.Mock()
        tg.call.side_effect = [[{'message_id': 2001}, {'message_id': 2002}], {'message_id': 2003}]
        run_once(FakeLLM({}), tg, now=timezone.now().replace(hour=4))
        self.assertEqual([c.args[0] for c in tg.call.call_args_list], ['sendMediaGroup', 'sendDocument'])
        self.assertEqual(len(tg.call.call_args_list[0].kwargs['media']), 2)
        self.assertEqual(DraftMessage.objects.filter(draft=self.draft).count(), 3)

    def test_later_duplicate_event_cancellation_blocks_existing_cards(self):
        from marketing.models import Signal
        from marketing.timeutil import KST
        now = timezone.now()
        today = now.astimezone(KST).date()
        WorkerState.put('dated_mode', 'live')
        signal = Signal.objects.create(kind='moment', key='first', book=self.book, title='가을 행사',
                                       happens_on=today, relevant=True, detail={'type':'event', 'status':'confirmed', 'onsite':True})
        self.proposal.signal = signal
        self.proposal.candidate_key = f'onsite:{signal.pk}:today'
        self.proposal.save()
        job = enqueue(self.draft, -200, 50)
        self.assertIsNotNone(job)
        Signal.objects.create(kind='moment', key='cancel-copy', book=self.book, title='가을 행사',
                              happens_on=today, relevant=True, detail={'type':'event', 'status':'cancelled', 'onsite':True})
        self.assertFalse(eligible(job, now))

    def test_peer_source_switch_is_rechecked(self):
        self.proposal.candidate_key = 'peer:10'
        self.proposal.save()
        self.assertIsNone(enqueue(self.draft, -200, 50))

    def test_daily_generation_budget_stops_third_attempt(self):
        one = enqueue(self.draft, -200, 50)
        self.assertTrue(reserve_illustration(one, timezone.now()))
        p = Proposal.objects.create(book=make_book(isbn='9781234567891'), kind='kit')
        d = Draft.objects.create(proposal=p, channel='instagram', extra=self.draft.extra)
        two = enqueue(d, -200, 51)
        self.assertTrue(reserve_illustration(two, timezone.now()))
        p2 = Proposal.objects.create(book=make_book(isbn='9781234567892'), kind='kit')
        d2 = Draft.objects.create(proposal=p2, channel='instagram', extra=self.draft.extra)
        three = enqueue(d2, -200, 52)
        self.assertFalse(reserve_illustration(three, timezone.now()))

    def test_toc_plan_without_extra_caption_uses_approved_original_label(self):
        from visuals.models import ApprovedImage
        from visuals.pipeline import build
        folder = Path(self.tmp.name) / 'sources'; folder.mkdir()
        Image.new('RGB', (600, 900), 'white').save(folder / 'toc.png')
        ApprovedImage.objects.create(book=self.book, kind='toc', path='sources/toc.png', label='목차 일부', source='승인된 원본')
        self.draft.extra = {'cards': [{'show': '시집 목차 면 사진 준비', 'text': ''}]}
        self.draft.save()
        job = enqueue(self.draft, -200, 50)
        build(job, FakeLLM({}), timezone.now())
        self.assertEqual(job.plan['cards'][0]['kind'], 'toc')
        self.assertEqual(job.plan['cards'][0]['text'], '목차 일부')
