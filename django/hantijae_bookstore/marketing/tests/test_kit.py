from datetime import date
from types import SimpleNamespace

from django.test import TestCase, override_settings

from marketing.hooks import seed
from marketing.kit import blog_has, build_kit, build_pending, links_text, missing_stores, pending_books
from marketing.models import Draft, Proposal
from marketing.tests.fakes import FakeLLM, make_book

DESC = '시인은 산불감시원 일을 시작했다. 몸을 통과한 흙과 풀의 이야기가 시가 될 때 나는 큰 위로를 받는다.'
REPLY = {
    'blog_title': '『나는 산속으로 더 깊이 들어간다 ― 최정 시집』',
    'blog_body': '시인은 산불감시원 일을 시작했습니다.\n\n“몸을 통과한 흙과 풀의 이야기가 시가 될 때 나는 큰 위로를 받는다.”',
    'instagram': '산불감시원이 된 시인이 산에서 만난 사람들.\n"지어낸 인용문이 여기에 있습니다"\n#한티재',
    'one_liners': ['산불감시원 시인이 만난 사람들', '이 한 줄은 스무 자를 훌쩍 넘어가 버리는 너무 긴 소개입니다', '몸을 통과한 흙과 노동의 시'],
    'summary_200': '청송 골짜기에서 농사지으며 시를 써 온 시인의 네 번째 시집이다.',
    'outreach': [{'who': '청송 지역 신문', 'why': '지역 시인'}, {'who': '귀농·귀촌 단체', 'why': '귀농 이야기'}],
    'letter': {'to': '청송 지역 신문', 'title': '신간 소식', 'body': '안녕하세요.\n\n도서출판 한티재 드림'},
    'caution': '재난을 소재로 쓰지 않았습니다.'}


@override_settings(SITE_URL='https://hantijae-bookstore.com')
class KitTest(TestCase):
    def setUp(self):
        self.book = make_book(description=DESC, aladin_url='https://www.aladin.co.kr/shop/wproduct.aspx?ItemId=1')
        self.today = date(2026, 9, 28)

    def test_blog_has_matches_title_in_post_titles(self):
        posts = [SimpleNamespace(title='『나는 산속으로 더 깊이 들어간다』 ― 최정 시집')]
        self.assertTrue(blog_has(self.book, posts))
        self.assertFalse(blog_has(self.book, []))
        self.assertFalse(blog_has(self.book, None))

    def test_links_text_uses_house_template_order(self):
        text = links_text(self.book)
        lines = text.splitlines()
        self.assertEqual(lines[:3], ['『나는 산속으로 더 깊이 들어간다』', '― 최정 시집', '최정 지음'])
        self.assertLess(text.index('교보문고'), text.index('알라딘'))
        self.assertLess(text.index('알라딘'), text.index('예스24'))
        self.assertTrue(lines[-1].endswith(f'/book={self.book.id}'))

    def test_missing_stores_lists_empty_saved_links(self):
        self.assertEqual(missing_stores(self.book), ['교보문고', '예스24'])

    def test_missing_stores_treats_untrusted_short_link_as_missing(self):
        self.book.kyobo_url = 'https://bit.ly/abc'
        self.assertEqual(missing_stores(self.book), ['교보문고', '예스24'])
        self.book.yes24_url = 'https://www.yes24.com/Product/Goods/1'
        self.assertEqual(missing_stores(self.book), ['교보문고'])

    def test_build_kit_creates_drafts_and_checks(self):
        p = build_kit(self.book, FakeLLM(REPLY), posts=[], today=self.today)
        channels = list(p.drafts.order_by('id').values_list('channel', flat=True))
        self.assertEqual(channels, [Draft.BLOG, Draft.INSTAGRAM, Draft.LINKS, Draft.SHORT, Draft.LETTER])
        blog = p.drafts.get(channel=Draft.BLOG)
        self.assertEqual(blog.title, '『나는 산속으로 더 깊이 들어간다』 ― 최정 시집')
        short = p.drafts.get(channel=Draft.SHORT).body
        self.assertNotIn('너무 긴 소개', short)
        self.assertIn('원문과 다른 인용', p.caution)
        self.assertIn('지어낸 인용문이 여기에 있습니다', p.caution)
        self.assertNotIn('자료에 없는 숫자', p.caution)
        self.assertEqual(p.extra, {'blog_exists': False, 'missing_stores': ['교보문고', '예스24']})

    def test_build_kit_flags_numbers_not_in_source(self):
        reply = dict(REPLY, instagram='벌써 1,000부가 나갔습니다.\n#한티재')
        p = build_kit(self.book, FakeLLM(reply), posts=[], today=self.today)
        self.assertIn('자료에 없는 숫자가 있어요. 확인해 주세요: 1000', p.caution)

    def test_build_kit_skips_blog_when_post_exists(self):
        posts = [SimpleNamespace(title='나는 산속으로 더 깊이 들어간다 출간')]
        p = build_kit(self.book, FakeLLM(REPLY), posts=posts, today=self.today)
        self.assertFalse(p.drafts.filter(channel=Draft.BLOG).exists())
        self.assertTrue(p.extra['blog_exists'])

    def test_build_kit_passes_upcoming_hooks_to_llm(self):
        seed()
        llm = FakeLLM(REPLY)
        build_kit(self.book, llm, posts=[], today=date(2026, 10, 1))
        self.assertIn('가을철 산불조심기간', llm.calls[0][1])

    def test_pending_books_are_recent_published_without_kit(self):
        old = make_book(title='오래된 책', published=date(2026, 6, 1), isbn='979-11-00000-04-1', author=None)
        draft = make_book(title='공개 전', is_published=False, isbn='979-11-00000-05-1', author=None)
        self.assertEqual(list(pending_books(self.today)), [self.book])
        build_pending(FakeLLM(REPLY), self.today, posts=[])
        self.assertEqual(list(pending_books(self.today)), [])
        self.assertNotIn(old, pending_books(self.today))
        self.assertNotIn(draft, pending_books(self.today))
