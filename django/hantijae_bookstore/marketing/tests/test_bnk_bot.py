from datetime import date, datetime
from unittest import mock

from django.test import TestCase

from intake.models import WorkerState
from marketing import bnk
from marketing.bot import Marketing
from marketing.models import Briefing, Proposal
from marketing.tests.fakes import FakeBnkClient, FakeLLM, FakeTG, make_book, make_sale
from marketing.tests.test_bot import ADMIN, GROUP, FakeHost
from marketing.timeutil import KST

NOW = datetime(2026, 9, 30, 10, 0, tzinfo=KST)


class BnkCommandTest(TestCase):
    def setUp(self):
        self.tg, self.host = FakeTG(), FakeHost()

    def m(self):
        return Marketing(self.tg, FakeLLM({}), self.host)

    def last(self):
        return self.tg.sent('send')[-1]['text']

    def test_switch_and_status(self):
        self.m().admin_command(ADMIN, '/bnk', 'on', now=NOW)
        self.assertEqual(self.last(), 'bnk_mode=on')
        self.m().admin_command(ADMIN, '/bnk', '', now=NOW)
        self.assertTrue(self.last().startswith('bnk_mode=on\n'))

    def test_now_collects_and_reports(self):
        c = FakeBnkClient()
        with mock.patch('marketing.bot.bnk.client_from_settings', return_value=c):
            self.m().admin_command(ADMIN, '/bnk', 'now', now=NOW)
        self.assertTrue(c.entered and c.exited)
        self.assertEqual(len(c.asked), 35)
        self.assertTrue(self.last().startswith('읽은 날 35일 · 판매 줄 0개'))
        self.assertEqual(WorkerState.get('bnk_last_run'), '2026-09-30')

    def test_login_failure_is_reported_not_raised_and_blocks_auto_login(self):
        with mock.patch('marketing.bot.bnk.client_from_settings', side_effect=bnk.BnkLoginError('전산망 로그인 실패')):
            self.m().admin_command(ADMIN, '/bnk', 'now', now=NOW)
        self.assertEqual(self.last(), '전산망 조회 실패: 전산망 로그인 실패')
        self.assertEqual(WorkerState.get('bnk_login_blocked'), '2026-09-30')

    def test_on_and_successful_now_lift_the_block(self):
        WorkerState.put('bnk_login_blocked', '2026-09-28')
        self.m().admin_command(ADMIN, '/bnk', 'on', now=NOW)
        self.assertFalse(WorkerState.get('bnk_login_blocked'))
        WorkerState.put('bnk_login_blocked', '2026-09-28')
        with mock.patch('marketing.bot.bnk.client_from_settings', return_value=FakeBnkClient()):
            self.m().admin_command(ADMIN, '/bnk', 'now', now=NOW)
        self.assertFalse(WorkerState.get('bnk_login_blocked'))

    def test_month_preview_sends_the_full_review_to_the_admin(self):
        with mock.patch('marketing.bot.bnk_sales.month_ready', return_value=True), \
                mock.patch('marketing.bot.bnk.client_from_settings', return_value=FakeBnkClient()), \
                mock.patch('marketing.bot.monthly.build', return_value='<b>📅 9월 돌아보기</b>') as build:
            self.m().admin_command(ADMIN, '/bnk', 'month', now=datetime(2026, 10, 2, 10, 0, tzinfo=KST))
        self.assertEqual(build.call_args[0][2], date(2026, 9, 1))
        preview = [c for c in self.tg.sent('send') if '돌아보기' in c['text']]
        self.assertEqual([(c['chat'], c['html']) for c in preview], [(ADMIN, True)])
        self.assertTrue(self.last().startswith('미리보기예요'))

    def test_monthly_switch(self):
        self.m().admin_command(ADMIN, '/bnk', 'monthly live', now=NOW)
        self.assertEqual((self.last(), WorkerState.get('monthly_mode')), ('monthly_mode=live', 'live'))

    def test_month_preview_checks_records_before_logging_in(self):
        with mock.patch('marketing.bot.bnk.client_from_settings') as factory:
            self.m().admin_command(ADMIN, '/bnk', 'month', now=NOW)
        factory.assert_not_called()
        self.assertEqual(self.last(), '지난달 하루하루를 다 읽은 기록이 아직 없어요')

    def test_briefing_gets_sales_line(self):
        WorkerState.put('marketing_mode', 'live')
        WorkerState.put('bnk_mode', 'on')
        book = make_book()
        make_sale(date(2026, 10, 2), 4, book=book, yes24=4)
        b = Briefing.objects.create(week_start=date(2026, 10, 5))
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, briefing=b, headline='항목', reason='이유', rank=1)
        self.assertTrue(self.m().send_briefing(b, datetime(2026, 10, 5, 9, 30, tzinfo=KST)))
        self.assertIn('\n\n📈 최근 7일(9월 26일~10월 2일) 4권', self.tg.sent('send')[0]['text'])
        self.assertEqual(self.tg.sent('send')[0]['chat'], GROUP)
