import json
import tempfile
from datetime import date

from django.core.management import call_command
from django.test import TestCase

from marketing.models import BookProfile, SalesSnapshot
from marketing.sales import collect_sales, latest, parse_product
from marketing.tests.fakes import make_book

ISBN = '9791192455952'


def page(isbn=ISBN, sp='455', short='1', review='1'):
    return (f"<a href='x.aspx?ItemId=400307943'>a</a><a href='y?ItemId=400307943'>b</a>"
            f"<div>Sales Point : <strong>{sp}</strong></div>"
            f"<a href='#K1_CommentReview'>100자평({short})</a><a href='#K1_MyReview'>리뷰({review})</a>"
            f"<li>ISBN : {isbn}</li>")


class ParseTest(TestCase):
    def test_parse_product_reads_numbers(self):
        p = parse_product(page(sp='7,307', short='13', review='2'), ISBN)
        self.assertEqual((p.sales_point, p.item_id, p.short_reviews, p.reviews), (7307, '400307943', 13, 2))

    def test_parse_rejects_isbn_mismatch(self):
        self.assertIsNone(parse_product(page(isbn='9791192455891'), ISBN))

    def test_parse_rejects_page_without_sales_point(self):
        self.assertIsNone(parse_product(f'<li>ISBN : {ISBN}</li>', ISBN))


class CollectTest(TestCase):
    def setUp(self):
        self.book = make_book()
        self.today = date(2026, 9, 28)

    def test_collect_saves_snapshot_and_item_id(self):
        saved, failed = collect_sales(self.today, get=lambda url: page(), sleep=lambda s: None)
        self.assertEqual((saved, failed), (1, []))
        self.assertEqual(SalesSnapshot.objects.get(book=self.book).sales_point, 455)
        self.assertEqual(BookProfile.objects.get(book=self.book).aladin_item_id, '400307943')

    def test_collect_is_idempotent_same_day(self):
        collect_sales(self.today, get=lambda url: page(), sleep=lambda s: None)
        saved, _ = collect_sales(self.today, get=lambda url: page(sp='999'), sleep=lambda s: None)
        self.assertEqual(saved, 0)
        self.assertEqual(SalesSnapshot.objects.get(book=self.book).sales_point, 455)

    def test_collect_skips_book_without_isbn_and_records_failures(self):
        make_book(title='ISBN 없는 책', isbn=None, author=None)
        broken = make_book(title='깨진 책', isbn='979-11-92455-89-1', author=None)

        def get(url):
            if '9791192455891' in url:
                raise TimeoutError('slow')
            return page()
        saved, failed = collect_sales(self.today, get=get, sleep=lambda s: None)
        self.assertEqual((saved, failed), (1, [broken.title]))

    def test_latest_returns_most_recent_on_or_before(self):
        SalesSnapshot.objects.create(book=self.book, date=date(2026, 9, 20), sales_point=400)
        SalesSnapshot.objects.create(book=self.book, date=date(2026, 9, 28), sales_point=455)
        self.assertEqual(latest(self.book, date(2026, 9, 27)).sales_point, 400)
        self.assertIsNone(latest(self.book, date(2026, 9, 1)))


class ImportTest(TestCase):
    def test_import_baseline_json(self):
        book = make_book()
        path = tempfile.mktemp(suffix='.json')
        with open(path, 'w') as f:
            json.dump({'collected_at': '2026-09-28T01:05:56+0900', 'rows': [
                {'id': book.id, 'isbn_match': True, 'sales_point': 455, 'short_reviews': 1, 'reviews': None},
                {'id': 99999, 'isbn_match': True, 'sales_point': 1},
                {'id': book.id + 1, 'isbn_match': False, 'sales_point': 3}]}, f)
        call_command('marketing_import_snapshots', path)
        snap = SalesSnapshot.objects.get(book=book)
        self.assertEqual((snap.date, snap.sales_point, snap.reviews), (date(2026, 9, 28), 455, 0))
        self.assertEqual(SalesSnapshot.objects.count(), 1)
