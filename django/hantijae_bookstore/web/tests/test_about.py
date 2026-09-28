from unittest import mock

from django.test import TestCase

from web.tests import factories as f


class AboutAnd404Test(TestCase):
    def setUp(self):
        patcher = mock.patch('web.views.blog.latest_posts', return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        f.book('가')
        f.book('나')
        f.book('비공개', is_published=False)

    def test_about(self):
        r = self.client.get('/hantijae')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('작고 약한 것들을 사랑한 선생님의 정신을 따라', body)
        self.assertIn('2010년 대구에서 문을 열어 지금까지 2종의 책을 펴냈습니다.', body)
        self.assertIn('<a href="/hantijae" aria-current="page">한티재 소개</a>', body)
        self.assertIn('misc/kiki.jpeg', body)
        self.assertIn('<title>한티재 소개 — 도서출판 한티재</title>', body)
        self.assertNotIn('지난 10년', body)

    def test_unknown_path_uses_site_404(self):
        for path in ('/does-not-exist', '/book=999999', '/series=999999'):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 404, path)
            body = r.content.decode()
            self.assertIn('찾으시는 페이지가 없습니다.', body)
            self.assertIn('<meta name="robots" content="noindex">', body)
