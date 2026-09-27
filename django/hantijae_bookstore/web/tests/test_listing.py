from datetime import date
from unittest import mock
from urllib.parse import quote

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from web.tests import factories as f


class ListingTest(TestCase):
    def setUp(self):
        patcher = mock.patch('web.views.blog.latest_posts', return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.series = f.series('단행본')
        self.books = [f.book(f'책 {i:02d}', date(2020, 1, 1 + i)) for i in range(30)]
        self.weather = f.book('내일 날씨, 어떻습니까?', date(2021, 7, 12), subtitle='기상학자가 들려주는 과학',
                              authors=(('김해동', 1),))
        self.slash = f.book('a/b 실험', date(2019, 1, 1))
        self.percent = f.book('100% 이야기', date(2019, 1, 2))

    def test_series_first_page(self):
        r = self.client.get(f'/series={self.series.id}')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertEqual(len(r.context['books']), 24)
        self.assertIn('<h1 class="page-title serif">단행본</h1>', body)
        self.assertIn('33권 · 최신순', body)
        self.assertIn(f'<a href="/series={self.series.id}" aria-current="page">단행본</a>', body)
        self.assertIn(f'href="/series={self.series.id}?page=2"', body)
        self.assertIn(f'<link rel="canonical" href="https://hantijae-bookstore.com/series={self.series.id}">', body)

    def test_series_second_page_canonical(self):
        r = self.client.get(f'/series={self.series.id}?page=2')
        self.assertEqual(len(r.context['books']), 9)
        self.assertIn(f'series={self.series.id}?page=2">', r.content.decode())

    def test_series_page_runs_public_series_query_once(self):
        """series_page picks the series from the same public_series() call used for nav —
        it must not query the public-series aggregate a second time for the header nav."""
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get(f'/series={self.series.id}')
        self.assertEqual(r.status_code, 200)
        count_queries = [q for q in ctx.captured_queries if 'COUNT(' in q['sql']]
        # one COUNT( comes from the public_series() annotate query (series list + nav, shared),
        # the other from Paginator.count() on series_books — never two public_series() calls.
        self.assertLessEqual(len(count_queries), 2, count_queries)

    def test_series_bad_page_is_404(self):
        for q in ('abc', '0', '3', '-1'):
            self.assertEqual(self.client.get(f'/series={self.series.id}?page={q}').status_code, 404, q)
        self.assertEqual(self.client.get('/series=999999').status_code, 404)
        self.assertEqual(self.client.get(f'/series={f.series("기타").id}').status_code, 404)

    def test_search_redirect_roundtrip_special_characters(self):
        for q, title in (('내일 날씨', '내일 날씨, 어떻습니까?'), ('a/b', 'a/b 실험'), ('100%', '100% 이야기')):
            r = self.client.get('/search', {'q': f'  {q} '})
            self.assertEqual(r.status_code, 302)
            self.assertEqual(r['Location'], '/search=' + quote(q, safe=''))
            page = self.client.get(r['Location'])
            self.assertEqual(page.status_code, 200, q)
            self.assertIn(title, page.content.decode())
            self.assertEqual(page.context['query'], q)
        self.assertEqual(self.client.get('/search', {'q': '   '})['Location'], '/')

    def test_search_by_author_and_noindex_and_query_kept_in_box(self):
        body = self.client.get('/search=' + quote('김해동')).content.decode()
        self.assertIn('내일 날씨, 어떻습니까?', body)
        self.assertIn('<meta name="robots" content="noindex">', body)
        self.assertIn('value="김해동"', body)

    def test_search_empty_result_suggests_recent(self):
        r = self.client.get('/search=' + quote('없는 말'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('‘없는 말’에 맞는 책을 찾지 못했습니다', r.content.decode())
        self.assertEqual(len(r.context['suggestions']), 6)

    def test_search_second_page_canonical_includes_page_number(self):
        word = '겨울책'
        for i in range(25):
            f.book(f'{word} {i:02d}', date(2022, 3, 1 + i))
        q = quote(word)
        r = self.client.get(f'/search={q}?page=2')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['books']), 1)
        self.assertIn(f'<link rel="canonical" href="https://hantijae-bookstore.com/search={q}?page=2">',
                      r.content.decode())
