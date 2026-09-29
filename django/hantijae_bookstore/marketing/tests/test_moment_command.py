from datetime import datetime
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from marketing.models import MomentScan, Signal
from marketing.tests.fakes import FakeLLM, make_book
from marketing.tests.test_moments import entry, new_item
from marketing.timeutil import KST


class MomentExtractCommandTest(TestCase):
    def setUp(self):
        make_book()
        self.old = entry(1, '금요일에 강연', at=datetime(2026, 9, 1, 10, 0, tzinfo=KST))
        self.new = entry(2, '금요일에 강연', at=datetime(2026, 9, 29, 10, 0, tzinfo=KST))

    def call(self, llm, *args):
        out = StringIO()
        deps = SimpleNamespace(llm=llm, tg=None, notion=None)
        with mock.patch('marketing.management.commands.moment_extract.build_deps', return_value=deps), \
                mock.patch('django.utils.timezone.now', return_value=datetime(2026, 9, 30, 5, 0, tzinfo=KST)):
            call_command('moment_extract', *args, '--no-photos', stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        llm = FakeLLM({'new': [new_item([self.new.id])]})
        text = self.call(llm, '--since', '2026-09-20', '--dry-run')
        self.assertIn('미리보기(저장 안 함)', text)
        self.assertIn('+ [author/confirmed] 2026-10-02', text)
        self.assertEqual((Signal.objects.count(), MomentScan.objects.count()), (0, 0))
        self.assertEqual(len(llm.calls), 1)

    def test_save_then_rerun_does_not_call_llm(self):
        llm = FakeLLM({'new': [new_item([self.new.id])]})
        text = self.call(llm, '--since', '2026-09-20', '--until', '2026-10-01')
        self.assertIn('저장함', text)
        self.assertEqual(Signal.objects.count(), 1)
        self.assertTrue(MomentScan.objects.filter(entry=self.new).exists())
        self.assertFalse(MomentScan.objects.filter(entry=self.old).exists())
        again = FakeLLM({'new': []})
        self.call(again, '--since', '2026-09-20')
        self.assertEqual(again.calls, [])

    def test_bad_date(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.call(FakeLLM({}), '--since', '9월 1일')
