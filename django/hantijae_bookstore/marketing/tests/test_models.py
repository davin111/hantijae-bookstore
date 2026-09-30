from datetime import date, datetime, timezone as dt_tz

from django.db import IntegrityError
from django.test import TestCase

from marketing.models import BookProfile, Draft, HookDate, Proposal, SalesSnapshot, Signal
from marketing.tests.fakes import make_book


class HookDateTest(TestCase):
    def test_next_on_annual_this_year(self):
        self.assertEqual(HookDate(name='커밍아웃의 날', month=10, day=11).next_on(date(2026, 9, 28)), date(2026, 10, 11))

    def test_next_on_includes_today(self):
        self.assertEqual(HookDate(name='x', month=9, day=28).next_on(date(2026, 9, 28)), date(2026, 9, 28))

    def test_next_on_rolls_to_next_year(self):
        self.assertEqual(HookDate(name='지구의 날', month=4, day=22).next_on(date(2026, 9, 28)), date(2027, 4, 22))

    def test_next_on_fixed_year_in_past_is_none(self):
        self.assertIsNone(HookDate(name='x', month=4, day=4, year=2026).next_on(date(2026, 9, 28)))

    def test_next_on_feb29_finds_next_leap_year(self):
        self.assertEqual(HookDate(name='x', month=2, day=29).next_on(date(2026, 9, 28)), date(2028, 2, 29))


class BookProfileTest(TestCase):
    def test_is_quiet_until_date_inclusive(self):
        p = BookProfile(book=make_book(), quiet_until=date(2026, 10, 31))
        self.assertTrue(p.is_quiet(date(2026, 10, 31)))
        self.assertFalse(p.is_quiet(date(2026, 11, 1)))
        self.assertFalse(BookProfile(book=p.book).is_quiet(date(2026, 1, 1)))


class SalesSnapshotTest(TestCase):
    def test_one_snapshot_per_book_per_day(self):
        book = make_book()
        SalesSnapshot.objects.create(book=book, date=date(2026, 9, 28), sales_point=455)
        with self.assertRaises(IntegrityError):
            SalesSnapshot.objects.create(book=book, date=date(2026, 9, 28), sales_point=456)


class DraftTest(TestCase):
    def test_label_is_korean_channel_name(self):
        self.assertEqual(Draft(channel=Draft.INSTAGRAM).label, '인스타 글')
        self.assertEqual(Draft(channel=Draft.LINKS).label, '서점 링크 공지')


class SelectionModelTest(TestCase):
    def test_selection_kind_and_announcement_record(self):
        from marketing.models import SelectionAnnouncement, Signal
        self.assertEqual(Signal.SELECTION, 'selection')
        self.assertIn(('selection', '공공 선정'), Signal._meta.get_field('kind').choices)
        a = SelectionAnnouncement.objects.create(key='kpipa:2145', source='kpipa', label='2026년 세종도서 교양부문',
                                                 url='https://www.kpipa.or.kr/p/g1_2/2145')
        self.assertEqual((a.matched, a.withdrawal, a.posted_on), (0, False, None))


class SocialModelTest(TestCase):
    def test_social_post_unique_per_platform_and_full_text(self):
        from datetime import datetime, timezone
        from django.db import transaction
        from marketing.models import SocialPost
        now = datetime(2026, 9, 29, 21, 20, tzinfo=timezone.utc)
        kw = dict(account='editor', posted_at=now, first_seen=now, last_seen=now)
        p = SocialPost.objects.create(platform='facebook', post_id='1', url='https://example.com/f/1', text='덧붙임',
                                      shared={'text': '원문'}, link={'title': '기사 제목'}, **kw)
        self.assertEqual(p.full_text(), '덧붙임\n원문\n기사 제목')
        SocialPost.objects.create(platform='instagram', post_id='1', url='https://example.com/i/1', **kw)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            SocialPost.objects.create(platform='facebook', post_id='1', url='https://example.com/f/1b', **kw)

    def test_signal_has_social_kind(self):
        from marketing.models import Signal
        self.assertEqual(Signal.SOCIAL, 'social')
        self.assertIn(('social', '운영진 SNS'), Signal._meta.get_field('kind').choices)


class MomentModelTest(TestCase):
    def setUp(self):
        from context.models import ContextEntry
        self.entry = ContextEntry.objects.create(key='tg:1:1', at=datetime(2026, 9, 29, 2, 0, tzinfo=dt_tz.utc), text='강연')

    def test_evidence_and_scan_follow_the_record(self):
        from django.db import IntegrityError, transaction
        from marketing.models import MomentScan, SignalEvidence
        s = Signal.objects.create(kind=Signal.MOMENT, key='moment:a', title='강연')
        SignalEvidence.objects.create(signal=s, entry=self.entry)
        MomentScan.objects.create(entry=self.entry, changed_at=self.entry.changed_at)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SignalEvidence.objects.create(signal=s, entry=self.entry)
        self.assertEqual(list(s.evidence.values_list('entry_id', flat=True)), [self.entry.id])
        self.entry.delete()
        self.assertFalse(SignalEvidence.objects.exists())
        self.assertFalse(MomentScan.objects.exists())
        self.assertTrue(Signal.objects.filter(pk=s.pk).exists())

    def test_midweek_proposal_kind(self):
        p = Proposal.objects.create(kind=Proposal.NOW, headline='『책』 ― 금요일 강연')
        self.assertEqual(p.get_kind_display(), '주중 제안')
        self.assertEqual(Signal(kind=Signal.MOMENT).get_kind_display(), '대화 속 계기')


class SignalKindTest(TestCase):
    def test_review_kind(self):
        self.assertEqual(Signal.REVIEW, 'review')
        self.assertEqual(dict(Signal._meta.get_field('kind').choices)['review'], '독자 서평')
