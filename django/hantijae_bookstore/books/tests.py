from datetime import date

from django.core.cache import cache
from rest_framework.test import APITestCase

from books.models import Book, BookSeries, Category, Series


def make_book(title='테스트 책', **kwargs):
    category = kwargs.pop('category', None) or Category.objects.get_or_create(name='에세이')[0]
    defaults = dict(full_price=15000, page_count=200, category=category, published_date=date(2026, 1, 1))
    defaults.update(kwargs)
    return Book.objects.create(title=title, **defaults)


class BookApiSmokeTest(APITestCase):
    def setUp(self):
        cache.clear()
        self.book = make_book()
        self.series = Series.objects.create(name='단행본', series_type=Series.NORMAL)
        BookSeries.objects.create(book=self.book, series=self.series)

    def test_list(self):
        res = self.client.get('/api/book/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual([b['id'] for b in res.json()], [self.book.id])

    def test_retrieve(self):
        res = self.client.get(f'/api/book/{self.book.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['title'], '테스트 책')

    def test_count(self):
        self.assertEqual(self.client.get('/api/book/count/').json(), {'count': 1})

    def test_series_detail(self):
        res = self.client.get(f'/api/book/series/{self.series.id}/')
        self.assertEqual([b['id'] for b in res.json()['books']], [self.book.id])
