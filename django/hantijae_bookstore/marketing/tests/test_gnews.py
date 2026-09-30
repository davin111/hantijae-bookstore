import json

from django.test import SimpleTestCase

from marketing import gnews

GN = 'https://news.google.com/rss/articles/CBMiABC?oc=5'
ORIGINAL = 'https://www.womennews.co.kr/news/articleView.html?idxno=282665'
PAGE = '<c-wiz><div jscontroller="x" data-n-a-sg="SIG" data-n-a-ts="1790730898"></div></c-wiz>'
RESP = ")]}'\n\n" + json.dumps([['wrb.fr', 'Fbv4je', json.dumps(['garturlres', ORIGINAL, 1]), None, None, None, '']])


def boom(*a, **kw):
    raise AssertionError('요청하면 안 됨')


class OriginalUrlTest(SimpleTestCase):
    def test_decodes_google_news_link_to_publisher_url(self):
        calls = []

        def get(url, timeout=None):
            calls.append(url)
            return PAGE

        def post(url, body):
            calls.append((url, body))
            return RESP
        self.assertEqual(gnews.original_url(GN, get=get, post=post), ORIGINAL)
        self.assertEqual(calls[0], 'https://news.google.com/rss/articles/CBMiABC')
        self.assertEqual(calls[1][0], gnews.BATCH_URL)
        self.assertIn('SIG', calls[1][1])
        self.assertIn('1790730898', calls[1][1])

    def test_other_links_are_left_alone_without_requests(self):
        for url in ('https://www.aladin.co.kr/m/bookfund/view.aspx?pid=3013', '', None):
            self.assertEqual(gnews.original_url(url, get=boom, post=boom), url)

    def test_falls_back_to_the_google_link_when_anything_fails(self):
        def raises(*a, **kw):
            raise OSError('막힘')
        cases = [(raises, lambda u, b: RESP),                      # 페이지를 못 읽음
                 (lambda u, timeout=None: '<html></html>', boom),  # 서명·시각이 없음(형식 바뀜)
                 (lambda u, timeout=None: PAGE, lambda u, b: 'garbage'),
                 (lambda u, timeout=None: PAGE, lambda u, b: RESP.replace(ORIGINAL, 'not-a-url'))]
        for get, post in cases:
            with self.assertLogs('intake', level='WARNING'):
                self.assertEqual(gnews.original_url(GN, get=get, post=post), GN)
