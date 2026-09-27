from datetime import date

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from books.constants import PUBLIC_SERIES_ORDER
from web import catalog, presenters
from web.tests import factories as f


class CatalogTest(TestCase):
    def setUp(self):
        cache.clear()
        for name in ('시선', '기타', '교양문고', '단행본'):
            f.series(name)
        self.a = f.book('가', date(2026, 1, 1))
        self.b = f.book('나', date(2026, 3, 1), authors=(('박한희', 1),))
        self.hidden = f.book('비공개', date(2026, 9, 1), is_published=False)
        self.poem = f.book('시집', date(2025, 5, 1), in_series='시선')
        self.other = f.book('기타 책', date(2020, 1, 1), in_series='기타')

    def test_public_series_follows_constant_order_with_published_counts(self):
        rows = catalog.public_series()
        self.assertEqual([s.name for s in rows], ['단행본', '교양문고', '시선'])
        self.assertEqual([s.book_count for s in rows], [2, 0, 1])
        self.assertEqual(PUBLIC_SERIES_ORDER[0], '단행본')

    def test_get_public_series_rejects_non_public(self):
        self.assertEqual(catalog.get_public_series(f.series('시선').id).name, '시선')
        self.assertIsNone(catalog.get_public_series(f.series('기타').id))
        self.assertIsNone(catalog.get_public_series(999999))

    def test_recent_books_newest_first_published_only_tie_by_id(self):
        tie = f.book('같은 날', date(2026, 3, 1))
        self.assertEqual([b.title for b in catalog.recent_books(3)], ['같은 날', '나', '가'])
        self.assertEqual([b.title for b in catalog.recent_books(2, offset=1)], ['나', '가'])
        self.assertNotIn(self.hidden, catalog.recent_books(10))
        self.assertTrue(tie.id > self.b.id)

    def test_series_books_and_same_series(self):
        dan = f.series('단행본')
        self.assertEqual([b.title for b in catalog.series_books(dan)], ['나', '가'])
        self.assertEqual(catalog.same_series_books(self.a, dan), [self.b])
        self.assertEqual(catalog.same_series_books(self.a, None), [])

    def test_book_series_returns_first_public_series(self):
        self.assertEqual(catalog.book_series(catalog.book_with_details(self.poem.id)).name, '시선')
        self.assertIsNone(catalog.book_series(catalog.book_with_details(self.other.id)))

    def test_book_with_details_includes_unpublished(self):
        self.assertEqual(catalog.book_with_details(self.hidden.id), self.hidden)
        self.assertIsNone(catalog.book_with_details(999999))

    def test_paginate(self):
        qs = catalog.series_books(f.series('단행본'))
        self.assertEqual(catalog.paginate(qs, None).number, 1)
        self.assertEqual(catalog.paginate(qs, '1').number, 1)
        self.assertIsNone(catalog.paginate(qs, 'abc'))
        self.assertIsNone(catalog.paginate(qs, '0'))
        self.assertIsNone(catalog.paginate(qs, '2'))
        self.assertEqual(list(catalog.paginate(qs.none(), None).object_list), [])

    def test_search_books_title_subtitle_author_distinct(self):
        f.book('다른 책', date(2024, 1, 1), subtitle='헌법 이야기', authors=(('박한희', 1), ('박한희2', 2)))
        self.assertEqual([b.title for b in catalog.search_books('헌법')], ['다른 책'])
        self.assertEqual([b.title for b in catalog.search_books('박한희')], ['나', '다른 책'])
        self.assertEqual(list(catalog.search_books('  ')), [])
        self.assertEqual(list(catalog.search_books('비공개')), [])

    def test_published_count(self):
        self.assertEqual(catalog.published_count(), 4)

    def test_recent_books_prefetches_authors(self):
        for i in range(8):
            f.book(f'책{i}', date(2019, 1, i + 1), authors=((f'A{i}', 1), (f'B{i}', 2)))
        with CaptureQueriesContext(connection) as ctx:
            books = catalog.recent_books(7)
            [presenters.authors_of(b) for b in books]
        self.assertLessEqual(len(ctx.captured_queries), 2)

    def test_series_api_uses_constant_order(self):
        names = [s['name'] for s in self.client.get('/api/book/series/').json()]
        self.assertEqual(names, ['단행본', '교양문고', '시선'])
