from datetime import date, datetime, timedelta

from django.test import TestCase

from intake.models import FundingCampaign
from marketing.funding import collect_funding, ends_on, is_stalled, parse_aladin_progress
from marketing.models import FundingSnapshot
from marketing.timeutil import KST

HTML = ('<div class="funding_wrap"> <div class="fd_price"><span class="price_t">6,768,000</span>원, 376권 펀딩 / '
        '목표 금액 5,000,000원 </div><div class="fd_dday"><span class="dday_t2">펀딩 중</span> '
        '(마감 2026-10-11, 출간예정 2026-10-19)</div>')
NOW = datetime(2026, 9, 28, 0, 0, tzinfo=KST)


def campaign(**kw):
    defaults = dict(platform='aladin', external_id='3013', url='https://www.aladin.co.kr/m/bookfund/view.aspx?pid=3013',
                    title='농부, 짠한 형', publisher='한티재', starts_at=NOW - timedelta(days=10),
                    ends_at=datetime(2026, 10, 12, 0, 0, tzinfo=KST), is_ours=True)
    defaults.update(kw)
    return FundingCampaign.objects.create(**defaults)


class FundingTest(TestCase):
    def test_parse_progress(self):
        p = parse_aladin_progress(HTML)
        self.assertEqual((p.amount, p.goal, p.books), (6768000, 5000000, 376))

    def test_parse_unknown_page_is_none(self):
        self.assertIsNone(parse_aladin_progress('<html>점검 중</html>'))

    def test_collect_saves_snapshot_for_live_ours_only(self):
        live = campaign()
        campaign(external_id='9', is_ours=False)
        campaign(external_id='10', ends_at=NOW - timedelta(days=1))
        self.assertEqual(collect_funding(date(2026, 9, 28), NOW, get=lambda url: HTML), 1)
        snap = FundingSnapshot.objects.get(campaign=live)
        self.assertEqual((snap.amount, snap.percent, snap.books), (6768000, 135, 376))

    def test_ends_on_is_day_before_ends_at(self):
        self.assertEqual(ends_on(campaign()), date(2026, 10, 11))

    def test_is_stalled_when_three_day_growth_under_two_percent(self):
        c = campaign()
        FundingSnapshot.objects.create(campaign=c, date=date(2026, 9, 25), amount=6700000, goal=5000000)
        FundingSnapshot.objects.create(campaign=c, date=date(2026, 9, 28), amount=6768000, goal=5000000)
        self.assertTrue(is_stalled(c, date(2026, 9, 28)))
        FundingSnapshot.objects.filter(date=date(2026, 9, 25)).update(amount=5000000)
        self.assertFalse(is_stalled(c, date(2026, 9, 28)))

    def test_is_stalled_false_without_history(self):
        self.assertFalse(is_stalled(campaign(), date(2026, 9, 28)))

    def test_is_stalled_false_with_single_old_snapshot(self):
        c = campaign()
        FundingSnapshot.objects.create(campaign=c, date=date(2026, 9, 20), amount=6700000, goal=5000000)
        self.assertFalse(is_stalled(c, date(2026, 9, 28)))

    def test_collect_funding_sleeps_between_requests_not_before_first(self):
        campaign(external_id='11')
        campaign(external_id='12')
        slept = []
        self.assertEqual(collect_funding(date(2026, 9, 28), NOW, get=lambda url: HTML, sleep=slept.append), 2)
        self.assertEqual(slept, [1.5])
