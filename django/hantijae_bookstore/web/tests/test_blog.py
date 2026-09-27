from datetime import date
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from web import blog

RSS = '''<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>도서출판 한티재</title>
<item><title><![CDATA[<내란 앞에서>가 출간되었습니다]]></title>
<link><![CDATA[https://blog.naver.com/hantijae_publisher/224000000001?fromRss=true&trackingCode=rss]]></link>
<category><![CDATA[편집 일기]]></category><pubDate>Fri, 10 Jul 2026 09:00:00 +0900</pubDate></item>
<item><title>두 번째</title><link>https://blog.naver.com/hantijae_publisher/2</link><pubDate>잘못된 날짜</pubDate></item>
<item><title></title><link>https://blog.naver.com/hantijae_publisher/3</link></item>
<item><title>세 번째</title><link>https://blog.naver.com/hantijae_publisher/4</link></item>
<item><title>네 번째</title><link>https://blog.naver.com/hantijae_publisher/5</link></item>
</channel></rss>'''.encode('utf-8')


class BlogTest(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_parse_rss(self):
        posts = blog.parse_rss(RSS)
        self.assertEqual([p.title for p in posts], ['<내란 앞에서>가 출간되었습니다', '두 번째', '세 번째'])
        self.assertEqual(posts[0].url, 'https://blog.naver.com/hantijae_publisher/224000000001')
        self.assertEqual(posts[0].date, date(2026, 7, 10))
        self.assertEqual(posts[0].category, '편집 일기')
        self.assertIsNone(posts[1].date)

    def test_latest_posts_caches_success(self):
        fetch = mock.Mock(return_value=RSS)
        self.assertEqual(len(blog.latest_posts(fetch)), 3)
        self.assertEqual(len(blog.latest_posts(fetch)), 3)
        fetch.assert_called_once()

    def test_latest_posts_failure_returns_empty_and_backs_off(self):
        fetch = mock.Mock(side_effect=OSError('timeout'))
        self.assertEqual(blog.latest_posts(fetch), [])
        self.assertEqual(blog.latest_posts(fetch), [])
        fetch.assert_called_once()

    def test_malformed_xml_is_empty(self):
        self.assertEqual(blog.latest_posts(mock.Mock(return_value=b'<rss><channel>')), [])
