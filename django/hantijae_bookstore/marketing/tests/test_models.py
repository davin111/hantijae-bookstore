from datetime import date

from django.db import IntegrityError
from django.test import TestCase

from marketing.models import BookProfile, Draft, HookDate, SalesSnapshot
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
