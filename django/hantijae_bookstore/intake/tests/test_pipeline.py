import json
import os
import tempfile
from datetime import date
from unittest import mock

from django.test import TestCase, override_settings
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
        self.bot.notify_family_or_admin.assert_not_called()

    def test_worker_iteration_closes_old_connections(self):
        tg = mock.Mock()
        tg.get_updates.return_value = [{'update_id': 7, 'message': {}}]
        deps = Deps(tg=tg, llm=FakeLLM(REPLY), bot=self.bot)
        with mock.patch('intake.pipeline.close_old_connections') as close:
            pipeline.run_iteration(deps)
        close.assert_called()
        self.assertEqual(WorkerState.get('telegram_offset'), 8)
        self.bot.handle_update.assert_called_once()

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
