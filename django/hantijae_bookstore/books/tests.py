from datetime import date
from unittest import mock

from django.core.cache import cache
from rest_framework.test import APITestCase

from books.models import Book, BookSeries, Category, Series
from books.preview import is_valid_preview_token, make_preview_token, preview_url


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



class PublishFilterTest(APITestCase):
    def setUp(self):
        cache.clear()
        self.public = make_book('공개 책')
        self.draft = make_book('비공개 초안', is_published=False)
        self.series = Series.objects.create(name='단행본', series_type=Series.NORMAL)
        for b in (self.public, self.draft):
            BookSeries.objects.create(book=b, series=self.series)

    def test_list_excludes_unpublished(self):
        ids = [b['id'] for b in self.client.get('/api/book/').json()]
        self.assertEqual(ids, [self.public.id])

    def test_search_excludes_unpublished(self):
        ids = [b['id'] for b in self.client.get('/api/book/', {'search': '책'}).json()]
        self.assertNotIn(self.draft.id, ids)
        ids = [b['id'] for b in self.client.get('/api/book/', {'search': '초안'}).json()]
        self.assertEqual(ids, [])

    def test_count_excludes_unpublished(self):
        self.assertEqual(self.client.get('/api/book/count/').json()['count'], 1)

    def test_series_and_category_exclude_unpublished(self):
        books = self.client.get(f'/api/book/series/{self.series.id}/').json()['books']
        self.assertEqual([b['id'] for b in books], [self.public.id])
        cats = self.client.get('/api/book/category/').json()
        all_ids = [b['id'] for c in cats for b in c['books']]
        self.assertNotIn(self.draft.id, all_ids)

    def test_retrieve_unpublished_requires_token(self):
        self.assertEqual(self.client.get(f'/api/book/{self.draft.id}/').status_code, 404)
        token = make_preview_token(self.draft.id)
        res = self.client.get(f'/api/book/{self.draft.id}/', {'preview': token})
        self.assertEqual(res.status_code, 200)

    def test_token_for_other_book_is_rejected(self):
        token = make_preview_token(self.public.id)
        self.assertEqual(self.client.get(f'/api/book/{self.draft.id}/', {'preview': token}).status_code, 404)

    def test_forged_and_expired_tokens(self):
        self.assertFalse(is_valid_preview_token(self.draft.id, f'{self.draft.id}:abc:def'))
        token = make_preview_token(self.draft.id)
        with mock.patch('django.core.signing.time.time', return_value=10 ** 11):
            self.assertFalse(is_valid_preview_token(self.draft.id, token))

    def test_preview_url_shape(self):
        url = preview_url(self.draft.id)
        self.assertTrue(url.startswith(f'https://hantijae-bookstore.com/book={self.draft.id}?preview='))
