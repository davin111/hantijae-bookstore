from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase

from marketing import web_sources as W
from marketing.review_search import SOURCE_LABEL
from marketing.timeutil import KST

# 2026-09-30 실제 알리미 피드를 줄인 것(두 번째 글은 가짜 기사)
FEED = '''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Google Alert - "도서출판 한티재"</title>
<entry><title type="html">단행본 - &lt;b&gt;도서출판 한티재&lt;/b&gt;</title>
<link href="https://www.google.com/url?rct=j&amp;sa=t&amp;url=https://hantijae-bookstore.com/series%3D5&amp;ct=ga&amp;usg=AO"/>
<published>2026-09-28T15:01:14Z</published><content type="html">단행본 107권 — &lt;b&gt;도서출판 한티재&lt;/b&gt;.</content></entry>
<entry><title type="html">[책과 사람] 「무궁화호를 위하여」 하승우</title>
<link href="https://www.google.com/url?rct=j&amp;sa=t&amp;url=https://news.example.com/a/1&amp;ct=ga"/>
<published>2026-09-27T01:00:00Z</published><content type="html">도서출판 한티재에서 펴낸 책</content></entry>
</feed>'''.encode()

YT = {'items': [{'id': {'kind': 'youtube#video', 'videoId': 'WZT0TDU3izg'},
                 'snippet': {'publishedAt': '2026-09-21T10:28:35Z',
                             'title': '[까칠한 언니들의 책수다] &quot;커밍아웃 스토리&quot; 성소수자부모모임',
                             'description': '커밍아웃 스토리, 성소수자와 그 부모들의 이야기', 'channelTitle': '전주FM'}},
                {'id': {'kind': 'youtube#channel', 'channelId': 'C'}, 'snippet': {'title': '채널'}}]}


class AlertsTest(SimpleTestCase):
    def test_unwrap(self):
        self.assertEqual(W.unwrap('https://www.google.com/url?rct=j&sa=t&url=https://news.example.com/a/1&ct=ga'),
                         'https://news.example.com/a/1')
        self.assertEqual(W.unwrap('https://news.example.com/b'), 'https://news.example.com/b')

    def test_parse_alerts(self):
        first, second = W.parse_alerts(FEED)
        self.assertEqual((first.source, first.url, first.title), ('web', 'https://hantijae-bookstore.com/series=5',
                                                                   '단행본 - 도서출판 한티재'))
        self.assertEqual((second.url, second.posted_on, second.snippet, second.where),
                         ('https://news.example.com/a/1', date(2026, 9, 27), '도서출판 한티재에서 펴낸 책', ''))

    def test_feeds_from_settings(self):
        self.assertEqual(W.feeds({'GOOGLE_ALERTS_FEEDS': '["https://g/1", "https://g/2"]'}), ['https://g/1', 'https://g/2'])
        self.assertEqual(W.feeds({'GOOGLE_ALERTS_FEEDS': 'not json'}), [])
        self.assertEqual(W.feeds({}), [])


class YoutubeTest(SimpleTestCase):
    def test_search_builds_request_and_parses_videos_only(self):
        calls = []
        posts = W.youtube_search('"커밍아웃 스토리" 성소수자부모모임', 'kk', datetime(2026, 9, 16, tzinfo=timezone.utc),
                                 lambda url, headers=None: calls.append(url) or YT)
        [p] = posts
        self.assertEqual((p.source, p.url, p.posted_on, p.where), ('youtube', 'https://www.youtube.com/watch?v=WZT0TDU3izg',
                                                                   date(2026, 9, 21), ''))
        self.assertEqual(p.title, '[까칠한 언니들의 책수다] "커밍아웃 스토리" 성소수자부모모임')
        q = parse_qs(urlsplit(calls[0]).query)
        self.assertEqual((q['type'], q['order'], q['maxResults'], q['publishedAfter'], q['key']),
                         (['video'], ['date'], ['25'], ['2026-09-16T00:00:00Z'], ['kk']))

    def test_youtube_search_with_kst_datetime(self):
        """KST 시간을 UTC로 변환해 publish 시간 필터가 맞다."""
        calls = []
        W.youtube_search('"x"', 'k', datetime(2026, 9, 16, tzinfo=KST),
                         lambda url, headers=None: calls.append(url) or {})
        q = parse_qs(urlsplit(calls[0]).query)
        self.assertEqual(q['publishedAfter'], ['2026-09-15T15:00:00Z'])

    def test_youtube_error_never_shows_the_key(self):
        def boom(url, headers=None):
            raise RuntimeError(f'403 Client Error for url: {url}')
        with self.assertRaises(W.SourceError) as ctx:
            W.youtube_search('"x"', 'SECRETKEY', datetime(2026, 9, 16, tzinfo=timezone.utc), boom)
        self.assertNotIn('SECRETKEY', str(ctx.exception))

    def test_labels(self):
        self.assertEqual((SOURCE_LABEL['web'], SOURCE_LABEL['youtube']), ('웹 언급', '유튜브'))
