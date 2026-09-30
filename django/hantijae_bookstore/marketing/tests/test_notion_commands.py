from datetime import date, datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from intake.models import WorkerState
from marketing import notion_sync as ns
from marketing.models import Briefing, Draft, Proposal
from marketing.tests.fakes import FakeNotion, FakeTG, make_book
from marketing.timeutil import KST


class NotionCommandsTest(TestCase):
    def setUp(self):
        self.fake, self.tg = FakeNotion(), FakeTG()
        patcher = [mock.patch(f'marketing.management.commands.{m}._clients', return_value=(self.fake, self.tg))
                   for m in ('marketing_notion_setup', 'marketing_notion_backfill')]
        for p in patcher:
            p.start()
            self.addCleanup(p.stop)

    def test_setup_once(self):
        out = StringIO()
        call_command('marketing_notion_setup', '--parent', 'parentpage', stdout=out)
        self.assertEqual((WorkerState.get(ns.DS), WorkerState.get('marketing_notion_db')), ('ds1', 'db1'))
        call_command('marketing_notion_setup', '--parent', 'parentpage', stdout=out)
        self.assertEqual(self.fake.calls.count('create_database'), 1)

    def test_backfill_builds_the_sent_briefing_and_redraws_its_buttons(self):
        WorkerState.put(ns.DS, 'ds1')  # 스위치는 off여도 된다
        b = Briefing.objects.create(week_start=date(2026, 9, 28), chat_id=-200, message_id=211,
                                    sent_at=datetime(2026, 9, 30, 11, 9, tzinfo=KST))
        ps = [Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=make_book(title=f'책{i}', isbn=f'979-11-00000-7{i}-1',
                                                                              author=None),
                                      briefing=b, headline=f'항목 {i}', rank=i, status=Proposal.SHOWN) for i in (1, 2)]
        for p in ps:
            Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='글')
        dry = StringIO()
        call_command('marketing_notion_backfill', '--week', '2026-09-28', '--dry-run', stdout=dry)
        self.assertIn('1. 항목 1', dry.getvalue())
        self.assertEqual(self.fake.pages, {})
        call_command('marketing_notion_backfill', '--week', '2026-09-28', stdout=StringIO())
        b.refresh_from_db()
        self.assertEqual((b.shown, b.notion['state']), ([ps[0].id, ps[1].id], 'done'))
        markup = self.tg.sent('markup')[0]
        self.assertEqual((markup['message_id'], markup['buttons']['inline_keyboard'][-1][0]['url']), (211, b.notion['url']))
