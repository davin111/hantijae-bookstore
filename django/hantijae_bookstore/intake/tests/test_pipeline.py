import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from books.models import Book, Category, Series
from intake import pipeline
from intake.deps import Deps
from intake.evaluation import compare
from intake.llm import LLMAuthError
from intake.models import BookDraft, IntakeSource, WorkerState

WORK = tempfile.mkdtemp()
REPLY = {'title': '새 책', 'authors': [{'name': '저자', 'role': '지은이'}], 'category': '에세이', 'size': '130×200',
         'page_count': 200, 'price': 15000, 'isbn': '979-11-92455-87-7', 'published_date': '2026-09-01',
         'short_description': '', 'description': ''}


class FakeLLM:
    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error

    def complete(self, system, user, attachments=()):
        if self.error:
            raise self.error
        return json.dumps(self.reply, ensure_ascii=False)


def telegram_source():
    d = tempfile.mkdtemp(dir=WORK)
    open(os.path.join(d, '보도자료_새책.pdf'), 'wb').write(b'%PDF')
    Image.new('RGB', (100, 150)).save(os.path.join(d, '새책_앞표지.jpg'))
    return IntakeSource.objects.create(kind=IntakeSource.TELEGRAM, title='t', local_dir=d, status=IntakeSource.QUEUED)


@override_settings(INTAKE={'WORK_DIR': WORK, 'DRIVE_SCAN_SECONDS': 600, 'DRIVE_STABLE_SECONDS': 1800})
class PipelineTest(TestCase):
    def setUp(self):
        Category.objects.create(name='에세이')
        Series.objects.create(name='단행본', series_type=Series.NORMAL)
        self.bot = mock.Mock()

    def deps(self, llm):
        return Deps(tg=mock.Mock(), llm=llm, bot=self.bot)

    def test_process_telegram_source_creates_draft_and_notifies(self):
        src = telegram_source()
        with mock.patch('intake.pipeline.best_local_text', return_value=('', 0.0, ''), create=True), \
                mock.patch('intake.extraction.best_local_text', return_value=('', 0.0, '')):
            draft = pipeline.process_source(src, self.deps(FakeLLM(REPLY)))
        self.assertEqual(draft.book.title, '새 책')
        self.assertEqual(IntakeSource.objects.get(pk=src.pk).status, IntakeSource.PROCESSED)
        self.bot.notify_draft.assert_called_once_with(draft)

    def test_auth_error_fails_source_and_alerts_admin_only(self):
        src = telegram_source()
        with mock.patch('intake.extraction.best_local_text', return_value=('', 0.0, '')):
            self.assertIsNone(pipeline.process_source(src, self.deps(FakeLLM(error=LLMAuthError('401')))))
        self.assertEqual(IntakeSource.objects.get(pk=src.pk).status, IntakeSource.FAILED)
        self.assertIn('인증', self.bot.notify_admin.call_args.args[0])
        self.bot.notify_reviewers_or_admin.assert_not_called()

    def test_worker_iteration_closes_old_connections(self):
        tg = mock.Mock()
        tg.get_updates.return_value = [{'update_id': 7, 'message': {}}]
        deps = Deps(tg=tg, llm=FakeLLM(REPLY), bot=self.bot)
        with mock.patch('intake.pipeline.close_old_connections') as close:
            pipeline.run_iteration(deps)
        close.assert_called()
        self.assertEqual(WorkerState.get('telegram_offset'), 8)
        self.bot.handle_update.assert_called_once()

    def test_skipped_drive_folders_are_reported_to_admin(self):
        tg = mock.Mock()
        tg.get_updates.return_value = []
        WorkerState.put('drive_autoscan', True)
        deps = Deps(tg=tg, llm=None, bot=self.bot, drive=mock.Mock(), drive_root='root')
        counts = {'new': 0, 'changed': 0, 'queued': 0, 'ignored': 1, 'skipped': [('보도자료_무지개를변호하다', 'old')]}
        with mock.patch('intake.pipeline.scan', return_value=counts), mock.patch('intake.pipeline.run_pending'):
            pipeline.run_iteration(deps)
        msg = self.bot.notify_admin.call_args.args[0]
        self.assertIn('보도자료_무지개를변호하다', msg)
        self.assertIn('/ingest old', msg)

    def test_iteration_survives_errors(self):
        tg = mock.Mock()
        tg.get_updates.side_effect = RuntimeError('network down')
        pipeline.run_iteration(Deps(tg=tg, llm=None, bot=self.bot), sleep=lambda s: None)
        self.bot.notify_admin.assert_called_once()


class CompareTest(TestCase):
    def test_compare_normalizes_formats(self):
        exp = {'title': '연대와 환대', 'isbn': '9791192455594', 'size': '130*185', 'page_count': 134,
               'full_price': 13000, 'published_date': '2024-10-01', 'authors': ['박지호'], 'series': '팸플릿 028'}
        act = dict(exp, isbn='979-11-92455-59-4', title='연대와  환대', series='팸플릿 28')
        self.assertTrue(all(compare(exp, act).values()))
        self.assertFalse(compare(exp, dict(act, page_count=135))['page_count'])


@override_settings(INTAKE={'WORK_DIR': WORK, 'DRIVE_SCAN_SECONDS': 600, 'DRIVE_STABLE_SECONDS': 1800})
class CrashResilienceTest(TestCase):
    def setUp(self):
        self.bot = mock.Mock()

    def test_update_that_crashed_the_worker_is_skipped_once(self):
        WorkerState.put('telegram_inflight', 7)
        tg = mock.Mock()
        tg.get_updates.return_value = [{'update_id': 7, 'message': {}}, {'update_id': 8, 'message': {}}]
        pipeline.run_iteration(Deps(tg=tg, llm=None, bot=self.bot))
        self.assertEqual(self.bot.handle_update.call_count, 1)          # 7은 건너뛰고 8만 처리
        self.assertEqual(WorkerState.get('telegram_offset'), 9)
        self.assertIsNone(WorkerState.get('telegram_inflight'))
        self.assertIn('7', self.bot.notify_admin.call_args_list[0].args[0])

    def test_interrupted_sources_are_retried_then_failed(self):
        a = IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='a', status=IntakeSource.PROCESSING, attempts=1)
        b = IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='b', status=IntakeSource.PROCESSING, attempts=3)
        pipeline.recover_interrupted(Deps(tg=None, llm=None, bot=self.bot))
        self.assertEqual(IntakeSource.objects.get(pk=a.pk).status, IntakeSource.QUEUED)
        self.assertEqual(IntakeSource.objects.get(pk=b.pk).status, IntakeSource.FAILED)
        self.bot.notify_admin.assert_called_once()

    def test_process_source_counts_attempts(self):
        src = IntakeSource.objects.create(kind=IntakeSource.TELEGRAM, title='t', local_dir=tempfile.mkdtemp(),
                                          status=IntakeSource.QUEUED)
        pipeline.process_source(src, Deps(tg=None, llm=FakeLLM(REPLY), bot=self.bot))
        self.assertEqual(IntakeSource.objects.get(pk=src.pk).attempts, 1)


class ContextPurgeTest(TestCase):
    def test_purge_runs_once_a_day_and_errors_do_not_stop_pending_work(self):
        bot = mock.Mock()
        deps = Deps(tg=mock.Mock(get_updates=mock.Mock(return_value=[])), llm=None, bot=bot)
        WorkerState.put('fund_autoscan', False)
        now = datetime(2026, 9, 29, 3, 0, tzinfo=dt_timezone.utc)
        with mock.patch('intake.pipeline.purge_context', side_effect=RuntimeError('boom')) as purge, \
                mock.patch('intake.pipeline.run_pending') as pending:
            pipeline.run_iteration(deps, now=now, sleep=lambda s: None)
            pipeline.run_iteration(deps, now=now + timedelta(hours=1), sleep=lambda s: None)
        self.assertEqual(purge.call_count, 1)
        self.assertEqual(pending.call_count, 2)
        self.assertIn('대화 기록 정리', bot.notify_admin.call_args.args[0])
        self.assertEqual(WorkerState.get('last_context_purge'), '2026-09-29')


class MarketingHookTest(TestCase):
    def test_run_iteration_calls_marketing_run_due(self):
        deps = Deps(tg=mock.Mock(get_updates=mock.Mock(return_value=[])), llm=None, bot=mock.Mock())
        now = timezone.now()
        with mock.patch('intake.pipeline.marketing_tasks.run_due') as run_due:
            pipeline.run_iteration(deps, now=now, sleep=lambda s: None)
        run_due.assert_called_once_with(deps, now)


class TelegramPollOutageTest(TestCase):
    """getUpdates 연결 오류는 연속 TG_ALERT_AFTER번째에만 알리고, 알린 끊김이 풀리면 '다시 연결됐어요'를 보낸다."""
    T0 = datetime(2026, 10, 2, 21, 7, tzinfo=dt_timezone.utc)   # 10-03 06:07 KST

    def setUp(self):
        from intake.telegram_api import TelegramError
        self.error = TelegramError('getUpdates: Read timed out')
        self.bot = mock.Mock()
        self.tg = mock.Mock()
        self.slept = []
        WorkerState.put('fund_autoscan', False)

    def poll(self, minute, ok=False):
        self.tg.get_updates.side_effect = None if ok else self.error
        self.tg.get_updates.return_value = []
        with mock.patch('intake.pipeline.marketing_tasks.run_due'), mock.patch('intake.pipeline.run_pending'):
            pipeline.run_iteration(Deps(tg=self.tg, llm=None, bot=self.bot), now=self.T0 + timedelta(minutes=minute),
                                   sleep=self.slept.append)

    def sent(self):
        return [c.args[0] for c in self.bot.notify_admin.call_args_list]

    def test_one_or_two_failures_are_not_announced(self):
        self.poll(0)
        self.poll(1)
        self.assertEqual(self.sent(), [])
        self.assertEqual(WorkerState.get('telegram_poll_outage')['fails'], 2)
        self.assertEqual(self.slept, [10, 10])

    def test_third_consecutive_failure_is_announced_once(self):
        for minute in range(5):
            self.poll(minute)
        self.assertEqual(len(self.sent()), 1)
        self.assertIn('텔레그램', self.sent()[0])
        self.assertIn('3번', self.sent()[0])
        self.assertIn('06:07', self.sent()[0])

    def test_recovery_after_announced_outage_says_reconnected_and_resets(self):
        for minute in range(3):
            self.poll(minute)
        self.poll(4, ok=True)
        self.assertEqual(len(self.sent()), 2)
        self.assertIn('다시 연결', self.sent()[1])
        self.assertIn('06:07~06:11', self.sent()[1])
        self.assertIsNone(WorkerState.get('telegram_poll_outage'))
        last = WorkerState.get('telegram_poll_last_outage')
        self.assertEqual(last['fails'], 3)
        self.assertEqual(last['since'], self.T0.isoformat())
        self.assertEqual(last['until'], (self.T0 + timedelta(minutes=4)).isoformat())

    def test_short_outage_recovers_silently_but_is_recorded(self):
        self.poll(0)
        self.poll(1, ok=True)
        self.assertEqual(self.sent(), [])
        self.assertIsNone(WorkerState.get('telegram_poll_outage'))
        self.assertEqual(WorkerState.get('telegram_poll_last_outage')['fails'], 1)

    def test_announcement_that_cannot_be_sent_is_retried_and_never_crashes(self):
        # 텔레그램이 완전히 끊기면 알림도 못 간다 — 워커를 죽이지 말고 다음 실패 때 다시 시도한다
        self.bot.notify_admin.side_effect = [self.error, None]
        for minute in range(5):
            self.poll(minute)
        self.assertEqual(self.bot.notify_admin.call_count, 2)   # 3번째 실패(보내기 실패) · 4번째(성공) · 5번째는 없음
        self.assertTrue(WorkerState.get('telegram_poll_outage')['alerted'])

    def test_poll_failure_skips_the_rest_of_the_iteration(self):
        with mock.patch('intake.pipeline.marketing_tasks.run_due') as run_due:
            self.tg.get_updates.side_effect = self.error
            pipeline.run_iteration(Deps(tg=self.tg, llm=None, bot=self.bot), now=self.T0, sleep=self.slept.append)
        run_due.assert_not_called()

    def test_other_errors_are_announced_at_once_even_if_sending_fails(self):
        self.tg.get_updates.side_effect = RuntimeError('bug')
        self.bot.notify_admin.side_effect = self.error
        pipeline.run_iteration(Deps(tg=self.tg, llm=None, bot=self.bot), now=self.T0, sleep=self.slept.append)
        self.bot.notify_admin.assert_called_once()
        self.assertIn('워커 오류', self.bot.notify_admin.call_args.args[0])


class MorningCheckTest(TestCase):
    """하루 한 번 08:30 KST 뒤 첫 바퀴: 살펴볼 것이 있을 때만 관리자 방에 한 메시지."""
    MORNING = datetime(2026, 10, 2, 23, 30, tzinfo=dt_timezone.utc)   # 10-03 08:30 KST

    def setUp(self):
        from ops import health
        self.warn = health.Row('review', '독자 서평', '04:30', state=health.WARN, reason='review_fail_naver_blog=2')
        self.fine = health.Row('sales', '알라딘 판매 지수', '06:00', state=health.OK)
        self.bot = mock.Mock()
        WorkerState.put('fund_autoscan', False)

    def run_at(self, now, rows):
        deps = Deps(tg=mock.Mock(get_updates=mock.Mock(return_value=[])), llm=None, bot=self.bot)
        with mock.patch('intake.pipeline.health.evaluate', return_value=rows), \
                mock.patch('intake.pipeline.marketing_tasks.run_due'), mock.patch('intake.pipeline.run_pending'):
            pipeline.run_iteration(deps, now=now, sleep=lambda s: None)

    def morning_notes(self):
        return [c for c in self.bot.notify_admin.call_args_list if '살펴볼 것' in c.args[0]]

    def test_nothing_is_sent_before_half_past_eight(self):
        self.run_at(self.MORNING - timedelta(minutes=1), [self.warn])
        self.assertEqual(self.morning_notes(), [])
        self.assertIsNone(WorkerState.get('ops_last_morning'))

    def test_things_worth_a_look_are_sent_once_a_day(self):
        self.run_at(self.MORNING, [self.warn, self.fine])
        self.run_at(self.MORNING + timedelta(hours=2), [self.warn, self.fine])
        notes = self.morning_notes()
        self.assertEqual(len(notes), 1)
        self.assertIn('독자 서평', notes[0].args[0])
        self.assertNotIn('알라딘', notes[0].args[0])
        self.assertIn('/ops/status', notes[0].args[0])
        self.assertTrue(notes[0].kwargs.get('html'))
        self.assertEqual(WorkerState.get('ops_last_morning'), '2026-10-03')

    def test_a_quiet_morning_sends_nothing(self):
        self.run_at(self.MORNING, [self.fine])
        self.bot.notify_admin.assert_not_called()

    def test_a_morning_note_that_cannot_be_sent_does_not_stop_the_loop(self):
        from intake.telegram_api import TelegramError
        self.bot.notify_admin.side_effect = TelegramError('sendMessage: timed out')
        deps = Deps(tg=mock.Mock(get_updates=mock.Mock(return_value=[])), llm=None, bot=self.bot)
        with mock.patch('intake.pipeline.health.evaluate', return_value=[self.warn]), \
                mock.patch('intake.pipeline.marketing_tasks.run_due') as run_due, \
                mock.patch('intake.pipeline.run_pending') as pending:
            pipeline.run_iteration(deps, now=self.MORNING, sleep=lambda s: None)
        run_due.assert_called_once()
        pending.assert_called_once()

    def test_a_broken_check_is_reported_and_does_not_stop_the_loop(self):
        deps = Deps(tg=mock.Mock(get_updates=mock.Mock(return_value=[])), llm=None, bot=self.bot)
        with mock.patch('intake.pipeline.health.evaluate', side_effect=RuntimeError('boom')), \
                mock.patch('intake.pipeline.marketing_tasks.run_due') as run_due, \
                mock.patch('intake.pipeline.run_pending'):
            pipeline.run_iteration(deps, now=self.MORNING, sleep=lambda s: None)
        run_due.assert_called_once()
        self.assertIn('아침 상태 점검', self.bot.notify_admin.call_args.args[0])
