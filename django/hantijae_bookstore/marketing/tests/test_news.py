import urllib.parse
from datetime import date

from django.test import TestCase

from marketing.models import Signal, WatchQuery
from marketing.news import collect_news, ensure_watch_queries, is_news, parse_rss
from marketing.tests.fakes import FakeLLM, make_book

RSS = """<?xml version="1.0" encoding="UTF-8"?><rss><channel>
<item><title>(10) 학교에서 혐오를 없애려면 - 법률신문</title><link>https://news.google.com/rss/articles/A1</link>
<pubDate>Wed, 09 Sep 2026 07:00:00 GMT</pubDate><source url="https://www.lawtimes.co.kr">법률신문</source></item>
<item><title>에피소드 2 - YouTube</title><link>https://news.google.com/rss/articles/B2</link>
<pubDate>Tue, 22 Sep 2026 07:00:00 GMT</pubDate><source url="https://www.youtube.com">YouTube</source></item>
<item><title>동명이인 소식 - 연합뉴스</title><link>https://news.google.com/rss/articles/C3</link>
<pubDate>Wed, 23 Sep 2026 07:00:00 GMT</pubDate><source url="https://www.yna.co.kr">연합뉴스</source></item>
</channel></rss>"""


class ParseTest(TestCase):
    def test_parse_strips_source_suffix(self):
        items = parse_rss(RSS)
        self.assertEqual(items[0].title, '(10) 학교에서 혐오를 없애려면')
        self.assertEqual((items[0].source, items[0].published), ('법률신문', date(2026, 9, 9)))

    def test_is_news_drops_video_and_blog_sources(self):
        self.assertEqual([a.source for a in parse_rss(RSS) if is_news(a)], ['법률신문', '연합뉴스'])


class CollectTest(TestCase):
    def setUp(self):
        self.book = make_book(title='무지개를 변호하다', subtitle='트랜스젠더 변호사 박한희의 삶과 생각',
                              published=date(2026, 6, 1), isbn='979-11-92455-80-8', author='박한희')

    def test_ensure_watch_queries_adds_recent_authors_once(self):
        make_book(title='오래된 책', published=date(2015, 1, 1), isbn='979-11-00000-00-1', author='옛 저자')
        ensure_watch_queries(date(2026, 9, 28))
        ensure_watch_queries(date(2026, 9, 28))
        self.assertEqual(list(WatchQuery.objects.values_list('query', flat=True)), ['박한희'])

    def test_collect_batches_llm_and_saves_verdicts(self):
        llm = FakeLLM({'items': [
            {'id': 0, 'same_person': True, 'evidence': '성소수자 인권 칼럼', 'relevant': True, 'sensitive': False,
             'summary': '법률신문 칼럼'},
            {'id': 1, 'same_person': False, 'evidence': '다른 분야', 'relevant': False, 'sensitive': False, 'summary': ''}]})
        made = collect_news(date(2026, 9, 28), llm, get=lambda url: RSS, sleep=lambda s: None)
        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(len(made), 2)
        good = Signal.objects.get(title='(10) 학교에서 혐오를 없애려면')
        self.assertTrue(good.relevant)
        self.assertEqual(good.book, self.book)
        self.assertFalse(Signal.objects.get(title='동명이인 소식').relevant)

    def test_collect_skips_already_seen_articles(self):
        llm = FakeLLM({'items': []})
        collect_news(date(2026, 9, 28), llm, get=lambda url: RSS, sleep=lambda s: None)
        again = collect_news(date(2026, 9, 28), llm, get=lambda url: RSS, sleep=lambda s: None)
        self.assertEqual(again, [])
        self.assertEqual(len(llm.calls), 1)

    def test_collect_survives_one_failing_query(self):
        WatchQuery.objects.create(query='정은정')

        def get(url):
            if urllib.parse.quote('"정은정"') in url:
                raise ConnectionError('down')
            return RSS
        made = collect_news(date(2026, 9, 28), FakeLLM({'items': []}), get=get, sleep=lambda s: None)
        self.assertEqual(len(made), 2)

    def test_collect_raises_when_every_query_fails(self):
        def boom(url):
            raise ConnectionError('down')
        with self.assertRaisesMessage(RuntimeError, '구글 뉴스 질의 1개가 모두 실패했어요'):
            collect_news(date(2026, 9, 28), FakeLLM({'items': []}), get=boom, sleep=lambda s: None)

    def test_sensitive_only_when_it_is_the_same_person(self):
        llm = FakeLLM({'items': [
            {'id': 0, 'same_person': True, 'relevant': False, 'sensitive': True, 'summary': '부고'},
            {'id': 1, 'same_person': False, 'relevant': False, 'sensitive': True, 'summary': '사고'}]})
        collect_news(date(2026, 9, 28), llm, get=lambda url: RSS, sleep=lambda s: None)
        self.assertTrue(Signal.objects.get(title='(10) 학교에서 혐오를 없애려면').sensitive)
        self.assertFalse(Signal.objects.get(title='동명이인 소식').sensitive)
