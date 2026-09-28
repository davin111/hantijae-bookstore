from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from web.tests import factories as f


class SeoTest(TestCase):
    def setUp(self):
        self.series = f.series('단행본')
        self.pub = f.book('공개')
        self.hidden = f.book('비공개', is_published=False)
        for i in range(10):
            f.book(f'책{i}')

    def test_sitemap_lists_public_pages_only(self):
        r = self.client.get('/sitemap.xml')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r['Content-Type'].startswith('application/xml'))
        body = r.content.decode()
        for loc in ('https://testserver/', 'https://testserver/books', 'https://testserver/hantijae',
                    f'https://testserver/series={self.series.id}',
                    f'https://testserver/book={self.pub.id}'):
            self.assertIn(f'<loc>{loc}</loc>', body)
        self.assertNotIn(f'/book={self.hidden.id}<', body)
        self.assertIn('<lastmod>', body)

    def test_sitemap_does_not_query_per_book(self):
        with CaptureQueriesContext(connection) as ctx:
            self.client.get('/sitemap.xml')
        self.assertLessEqual(len(ctx.captured_queries), 4)

    def test_robots(self):
        r = self.client.get('/robots.txt')
        self.assertEqual(r['Content-Type'], 'text/plain; charset=utf-8')
        self.assertEqual(r.content.decode(), 'User-agent: *\nAllow: /\nDisallow: /go/\n\n'
                                             'Sitemap: https://hantijae-bookstore.com/sitemap.xml\n')
