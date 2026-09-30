import urllib.parse
from datetime import date

from django.test import TestCase
from django.utils import timezone

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
        # 판정만 본다: 좁히기는 이미 끝난 질의로 둔다(좁히기는 NarrowTest)
        WatchQuery.objects.create(query='박한희', book=self.book, narrowed_at=timezone.now())

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


class NarrowTest(TestCase):
    """동명이인이 많은 이름(마포구청장 박강수, 야구선수 최정…)은 이름만으로 찾으면 남의 기사에 묻힌다(2026-09-30:
    90건 중 관련 6건). 저자마다 분야 낱말을 한 번 골라 검색어에 덧붙인다."""

    def setUp(self):
        self.book = make_book(title='그리운 바람이 나를 불러', subtitle='박강수 노래시집', published=date(2026, 2, 9),
                              isbn='979-11-92455-82-2', author='박강수',
                              description='싱어송라이터 박강수의 노래시집. 직접 쓴 노랫말 81편.')
        self.urls = []

    def get(self, url):
        self.urls.append(urllib.parse.unquote(url))
        return RSS

    def collect(self, llm):
        return collect_news(date(2026, 9, 28), llm, get=self.get, sleep=lambda s: None)

    def test_query_uses_saved_narrow(self):
        WatchQuery.objects.create(query='박강수', book=self.book, narrow='(가수 OR 노래)', narrowed_at=timezone.now())
        self.collect(FakeLLM({'items': []}))
        self.assertIn('"박강수" (가수 OR 노래) when:14d', self.urls[0])

    def test_new_query_is_narrowed_once_with_words_title_and_publisher(self):
        llm = FakeLLM([{'items': [{'id': 0, 'words': ['가수', '노래', '포크']}]}, {'items': []}, {'items': []}])
        self.collect(llm)
        w = WatchQuery.objects.get(query='박강수')
        # "박강수의": '[하승우의 풀뿌리]' 같은 저자 칼럼은 분야 낱말 없이도 잡히게(2026-09-30 실측: 관련 6건 중 칼럼 2건이 빠짐)
        self.assertEqual(w.narrow, '(가수 OR 노래 OR 포크 OR 한티재 OR "그리운 바람이 나를 불러" OR "박강수의")')
        self.assertIsNotNone(w.narrowed_at)
        self.assertIn('"박강수" (가수 OR 노래 OR 포크 OR 한티재 OR "그리운 바람이 나를 불러" OR "박강수의") when:14d',
                      self.urls[0])
        self.assertIn('박강수', llm.calls[0][1])
        self.assertIn('싱어송라이터', llm.calls[0][1])  # 책 소개를 근거로 고른다
        self.collect(llm)
        self.assertEqual(len(llm.calls), 2)  # 두 번째 수집에는 좁히기 호출이 없다(판정은 새 기사가 없어 건너뜀)

    def test_unsafe_words_are_dropped(self):
        words = ['가수', '"따옴표"', 'OR', '-구청장', '(괄호)', '너무너무너무너무길어서검색에못쓰는낱말', '가수', '박강수', '노래 공연']
        llm = FakeLLM([{'items': [{'id': 0, 'words': words}]}, {'items': []}])
        self.collect(llm)
        self.assertEqual(WatchQuery.objects.get(query='박강수').narrow,
                         '(가수 OR 한티재 OR "그리운 바람이 나를 불러" OR "박강수의")')

    def test_no_usable_words_keeps_plain_query_and_does_not_ask_again(self):
        llm = FakeLLM([{'items': [{'id': 0, 'words': []}]}, {'items': []}, {'items': []}])
        self.collect(llm)
        w = WatchQuery.objects.get(query='박강수')
        self.assertEqual(w.narrow, '')
        self.assertIsNotNone(w.narrowed_at)
        self.assertIn('"박강수" when:14d', self.urls[0])

    def test_narrow_failure_keeps_plain_query_and_retries_next_time(self):
        llm = FakeLLM(['아님', '아님', {'items': []}])  # 좁히기: 잘못된 JSON 두 번(다시 묻기 포함) → 판정은 그대로
        made = self.collect(llm)
        w = WatchQuery.objects.get(query='박강수')
        self.assertEqual((w.narrow, w.narrowed_at), ('', None))
        self.assertIn('"박강수" when:14d', self.urls[0])
        self.assertEqual(len(made), 2)

    def test_malformed_narrow_reply_does_not_stop_collection(self):
        for reply in ({'items': None}, {'items': [{'id': [0], 'words': ['가수']}]}, {'items': '글자'}):
            WatchQuery.objects.all().delete()
            Signal.objects.all().delete()
            made = self.collect(FakeLLM([reply, {'items': []}]))
            w = WatchQuery.objects.get(query='박강수')
            self.assertEqual((w.narrow, w.narrowed_at, len(made)), ('', None, 2))

    def test_queries_without_book_are_not_narrowed(self):
        ensure_watch_queries(date(2026, 9, 28))
        WatchQuery.objects.filter(query='박강수').update(narrowed_at=timezone.now())
        WatchQuery.objects.create(query='정은정')
        llm = FakeLLM({'items': []})
        self.collect(llm)
        self.assertEqual(len(llm.calls), 1)  # 판정만
        self.assertIsNone(WatchQuery.objects.get(query='정은정').narrowed_at)

    def test_same_person_is_kept_in_detail(self):
        WatchQuery.objects.create(query='박강수', book=self.book, narrowed_at=timezone.now())
        llm = FakeLLM({'items': [{'id': 0, 'same_person': False, 'relevant': False, 'sensitive': False, 'summary': ''}]})
        self.collect(llm)
        self.assertIs(Signal.objects.get(title='(10) 학교에서 혐오를 없애려면').detail['same_person'], False)
