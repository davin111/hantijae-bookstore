import re
from datetime import date, timedelta
from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from web.blog import BlogPost
from web.models import Notice
from web.tests import factories as f

POSTS = [BlogPost('<내란 앞에서>가 출간되었습니다', 'https://blog.naver.com/hantijae_publisher/1', date(2026, 7, 10), '편집 일기')]


class HomeTest(TestCase):
    def setUp(self):
        patcher = mock.patch('web.views.blog.latest_posts', return_value=POSTS)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ('단행본', '교양문고', '시선'):
            f.series(name)
        self.old = [f.book(f'오래된 책 {i}', date(2020, 1, i + 1)) for i in range(14)]
        self.hero = f.book('나는 산속으로 더 깊이 들어간다', date(2026, 8, 21), in_series='시선', subtitle='최정 시집',
                           short_description='**도시** 생활 이십 년 만에', authors=(('최정', 1),))
        f.book('비공개 초안', date(2026, 9, 1), is_published=False)

    def test_hero_recent_and_shelf(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertEqual(r.context['hero'], self.hero)
        self.assertIn('새로 나온 책 · 2026년 8월', body)
        self.assertIn('최정 지음 · 시선', body)
        self.assertIn('도시 생활 이십 년 만에', body)
        self.assertNotIn('**', body)
        self.assertNotIn('비공개 초안', body)
        self.assertEqual(len(r.context['recent']), 6)
        self.assertNotIn(self.hero, r.context['recent'])
        self.assertEqual(r.context['shelf_series'].name, '단행본')
        self.assertEqual(len(r.context['shelf_books']), 12)
        self.assertIn('단행본 14권 모두 보기', body)
        self.assertIn(f'/go/{self.hero.id}/aladin', body)
        self.assertIn('책 소개 보기', body)

    def test_nav_order_matches_operators_list(self):
        for name in ('시의숲', '팸플릿', '산문선', '기타'):
            f.series(name)
        body = self.client.get('/').content.decode()
        nav = body[body.index('<nav class="section-nav"'):]
        nav = nav[:nav.index('</nav>')]
        self.assertEqual(re.findall(r'>([^<>]+)</a>', nav),
                         ['신간', '전체 보기', '단행본', '교양문고', '팸플릿', '산문선', '시선', '시의숲', '한티재 소개'])

    def test_recent_block_links_to_all_books(self):
        self.assertIn('<a href="/books">펴낸 책 모두 보기 →</a>', self.client.get('/').content.decode())

    def test_nav_footer_and_meta(self):
        body = self.client.get('/').content.decode()
        self.assertIn('<a href="/" aria-current="page">신간</a>', body)
        self.assertIn('https://blog.naver.com/hantijae_publisher', body)
        self.assertNotIn('hanti_books', body)
        self.assertIn('492길 15 (2층)', body)
        self.assertIn('<title>도서출판 한티재</title>', body)
        self.assertIn('<link rel="canonical" href="https://hantijae-bookstore.com/">', body)
        self.assertIn('<meta property="og:image" content="https://hantijae-bookstore.com/django_static/web/og-default.png">', body)
        self.assertIn('작고 약한 것들을 사랑한', body)
        self.assertIn('pretendardvariable-dynamic-subset.min.css', body)
        self.assertIn('family=Gowun+Batang', body)

    def test_notice_bar_only_when_active(self):
        self.assertNotIn('notice-bar', self.client.get('/').content.decode())
        Notice.objects.create(message='『농부, 짠한 형』 알라딘 북펀드 진행 중', link_url='https://www.aladin.co.kr/m/bookfund/view.aspx?pid=3013',
                              link_label='함께하기', ends_at=timezone.now() + timedelta(days=3))
        body = self.client.get('/').content.decode()
        self.assertIn('notice-bar', body)
        self.assertIn('함께하기 →', body)

    def test_blog_posts_rendered(self):
        body = self.client.get('/').content.decode()
        self.assertIn('&lt;내란 앞에서&gt;가 출간되었습니다', body)
        self.assertIn('편집 일기 · 2026년 7월 10일', body)

    def test_analytics_only_when_configured(self):
        self.assertNotIn('wcslog.js', self.client.get('/').content.decode())
        with override_settings(NAVER_ANALYTICS_ID='abc123'):
            body = self.client.get('/').content.decode()
        self.assertIn('wcslog.js', body)
        self.assertIn('abc123', body)

    def test_query_budget(self):
        with CaptureQueriesContext(connection) as ctx:
            self.client.get('/')
        self.assertLessEqual(len(ctx.captured_queries), 9)


class EmptyHomeTest(TestCase):
    @mock.patch('web.views.blog.latest_posts', return_value=[])
    def test_empty_catalog_renders(self, _):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context['hero'])
