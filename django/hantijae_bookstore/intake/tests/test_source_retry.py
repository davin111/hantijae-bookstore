from unittest import mock
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from intake import drive, pipeline
from intake.deps import Deps
from intake.models import BookDraft, IntakeSource
from intake.tests import test_bot as helpers
from intake.tests.test_drive import FakeDrive, tree


@override_settings(INTAKE=helpers.CONFIG)
class SourceRetryTest(TestCase):
    setUp = helpers.BotTest.setUp
    bot = helpers.BotTest.bot

    def source(self, **extra):
        return IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='보도자료_새책',
            drive_folder_id=extra.pop('drive_folder_id', 'bk'), status=extra.pop('status', IntakeSource.FAILED),
            attempts=3, error='추출 실패', **extra)

    def test_explicit_retry_queues_failed_source_once_and_clears_attempts(self):
        src = self.source()
        bot = self.bot()
        bot.handle_update(helpers.msg(helpers.ADMIN, f'/retry {src.pk}', chat_type='private'))
        src.refresh_from_db()
        self.assertEqual((src.status, src.attempts, src.error), (IntakeSource.QUEUED, 0, ''))
        src.status, src.attempts, src.error = IntakeSource.PROCESSING, 1, '처리 중 메모'
        src.save()
        bot.handle_update(helpers.msg(helpers.ADMIN, f'/retry {src.pk}', chat_type='private'))
        src.refresh_from_db()
        self.assertEqual((src.status, src.attempts, src.error), (IntakeSource.PROCESSING, 1, '처리 중 메모'))

    def test_retry_preserves_every_nonfailed_state(self):
        for status, _ in IntakeSource.STATUS_CHOICES:
            if status == IntakeSource.FAILED:
                continue
            with self.subTest(status=status):
                src = IntakeSource.objects.create(kind=IntakeSource.DRIVE, title=status,
                    status=status, attempts=2, error='보존할 메모')
                self.bot().handle_update(helpers.msg(helpers.ADMIN, f'/retry {src.pk}', chat_type='private'))
                src.refresh_from_db()
                self.assertEqual((src.status, src.attempts, src.error), (status, 2, '보존할 메모'))

    def test_retry_failed_source_with_existing_draft_does_not_create_another(self):
        src = self.draft.source
        src.status, src.attempts, src.error = IntakeSource.FAILED, 3, '이전 처리 메모'
        src.save()
        self.bot().handle_update(helpers.msg(helpers.ADMIN, f'/retry {src.pk}', chat_type='private'))
        src.refresh_from_db()
        self.assertEqual((src.status, src.attempts, src.error), (IntakeSource.FAILED, 3, '이전 처리 메모'))
        self.assertEqual(BookDraft.objects.filter(source=src).count(), 1)
        self.assertIn('초안', self.tg.texts()[-1])

    def test_reviewer_cannot_retry_a_source(self):
        src = self.source()
        self.bot().handle_update(helpers.msg(helpers.GROUP, f'/retry {src.pk}'))
        src.refresh_from_db()
        self.assertEqual((src.status, src.attempts, src.error), (IntakeSource.FAILED, 3, '추출 실패'))

    def test_ingest_retry_resets_failed_attempts(self):
        src = self.source()
        retried = drive.ingest(FakeDrive(tree()), 'bk')
        self.assertEqual(retried.pk, src.pk)
        src.refresh_from_db()
        self.assertEqual((src.status, src.attempts, src.error), (IntakeSource.QUEUED, 0, ''))

    def test_new_folder_ingest_creates_only_one_queued_source(self):
        src = drive.ingest(FakeDrive(tree()), 'bk')
        self.assertEqual((src.status, src.attempts, src.title), (IntakeSource.QUEUED, 0, '보도자료_새책'))
        with self.assertRaises(ValueError):
            drive.ingest(FakeDrive(tree()), 'bk')
        self.assertEqual(IntakeSource.objects.filter(drive_folder_id='bk').count(), 1)

    def test_background_scan_leaves_failed_source_for_explicit_retry(self):
        src = self.source(stable_since=timezone.now() - timedelta(hours=1))
        drive.scan(FakeDrive(tree()), 'root')
        src.refresh_from_db()
        self.assertEqual((src.status, src.attempts, src.error), (IntakeSource.FAILED, 3, '추출 실패'))

    def test_ingest_cannot_requeue_processing_or_processed_source(self):
        src = self.source()
        for status in (IntakeSource.QUEUED, IntakeSource.PROCESSING, IntakeSource.PROCESSED):
            with self.subTest(status=status):
                src.status = status
                src.save()
                with self.assertRaises(ValueError):
                    drive.ingest(FakeDrive(tree()), 'bk')
                src.refresh_from_db()
                self.assertEqual((src.status, src.attempts, src.error), (status, 3, '추출 실패'))

    def test_ingest_preserves_existing_draft_even_if_source_status_is_stale(self):
        src = self.draft.source
        src.drive_folder_id, src.status = 'bk', IntakeSource.FAILED
        src.save()
        with self.assertRaises(ValueError):
            drive.ingest(FakeDrive(tree()), 'bk')
        src.refresh_from_db()
        self.assertEqual(src.status, IntakeSource.FAILED)
        self.assertEqual(BookDraft.objects.filter(source=src).count(), 1)

    def test_ingest_command_explains_processing_without_requeueing(self):
        folder_id = 'bk1234567890'
        src = self.source(status=IntakeSource.PROCESSING, drive_folder_id=folder_id)
        entries = tree()
        entries['y2026'][0]['id'] = folder_id
        entries[folder_id] = entries.pop('bk')
        ops = drive.DriveOpsImpl(FakeDrive(entries), 'root')
        self.bot(drive_ops=ops).handle_update(helpers.msg(
            helpers.ADMIN, f'/ingest {folder_id}', chat_type='private'))
        src.refresh_from_db()
        self.assertEqual(src.status, IntakeSource.PROCESSING)
        self.assertIn('처리 중', self.tg.texts()[-1])

    def test_stale_worker_snapshot_cannot_process_an_already_claimed_source(self):
        src = self.source(status=IntakeSource.QUEUED)
        IntakeSource.objects.filter(pk=src.pk).update(status=IntakeSource.PROCESSING, attempts=4)
        deps = Deps(tg=None, llm=None, bot=mock.Mock(), drive=mock.Mock())
        with mock.patch('intake.pipeline.download_folder') as download:
            result = pipeline.process_source(src, deps)
        self.assertIsNone(result)
        download.assert_not_called()
        src.refresh_from_db()
        self.assertEqual((src.status, src.attempts), (IntakeSource.PROCESSING, 4))

    def test_restart_after_committed_draft_preserves_it_without_redelivery(self):
        src = self.draft.source
        src.status, src.attempts = IntakeSource.PROCESSING, 1
        src.save()
        deps = Deps(tg=None, llm=None, bot=mock.Mock())
        pipeline.recover_interrupted(deps)
        src.refresh_from_db()
        self.assertEqual(src.status, IntakeSource.PROCESSED)
        self.assertEqual(pipeline.run_pending(deps), 0)
        self.assertEqual(BookDraft.objects.filter(source=src).count(), 1)
        deps.bot.notify_draft.assert_not_called()

    def test_queued_source_with_committed_draft_is_not_extracted_again(self):
        src = self.draft.source
        src.status = IntakeSource.QUEUED
        src.save()
        deps = Deps(tg=None, llm=None, bot=mock.Mock(), drive=mock.Mock())
        with mock.patch('intake.pipeline.download_folder') as download:
            pipeline.process_source(src, deps)
        download.assert_not_called()
        src.refresh_from_db()
        self.assertEqual(src.status, IntakeSource.PROCESSED)
        self.assertEqual(BookDraft.objects.filter(source=src).count(), 1)
        deps.bot.notify_draft.assert_not_called()
