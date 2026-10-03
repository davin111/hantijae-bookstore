from datetime import date, datetime

from django.test import TestCase

from marketing import ads, monthly
from marketing.tests.fakes import make_ad, make_book
from marketing.timeutil import KST

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=KST)
SEPT = [date(2026, 9, 22), date(2026, 9, 23)]


def card(*items):
    return ads.card_text(list(items), NOW, fetch=lambda since, until: {'facebook': []})


class CardLinkTest(TestCase):
    def test_heading_links_to_the_post(self):
        ad = make_ad(book=make_book(), days=SEPT, post_url='https://www.facebook.com/hantijae/posts/1?a=1&b=2')
        self.assertIn('<a href="https://www.facebook.com/hantijae/posts/1?a=1&amp;b=2">'
                      '<b>『나는 산속으로 더 깊이 들어간다』 글</b></a> (페이스북)', card(ad))

    def test_no_link_without_a_url_or_with_an_odd_scheme(self):
        plain = make_ad(ad_id='1', post_id='111_1', days=SEPT, post_text='북토크 안내')
        odd = make_ad(ad_id='2', post_id='111_2', days=SEPT, post_text='모집 안내', post_url='javascript:alert(1)')
        text = card(plain, odd)
        self.assertNotIn('<a ', text)
        self.assertIn('<b>「북토크 안내」 글</b> (페이스북)', text)

    def test_two_ads_with_the_same_name_get_the_start_of_their_posts(self):
        a = make_ad(ad_id='1', post_id='111_1', days=SEPT, book_title='농부, 짠한 형',
                    post_text='한티재에서 준비하고 있는 다음 책은 <농부, 짠한 형>입니다.', post_url='https://f/1')
        b = make_ad(ad_id='2', post_id='111_2', days=SEPT, book_title='농부, 짠한 형',
                    post_text='“재미없을수록 재밌게 살자!” 두물머리 20년차 유기농 농부', post_url='https://f/2')
        text = card(a, b)
        self.assertIn('<a href="https://f/1"><b>『농부, 짠한 형』 글 「한티재에서 준비하고 있는 다음 책은…」</b></a>', text)
        self.assertIn('<a href="https://f/2"><b>『농부, 짠한 형』 글 「“재미없을수록 재밌게 살자!”…」</b></a>', text)

    def test_a_single_ad_has_no_snippet(self):
        ad = make_ad(days=SEPT, book_title='농부, 짠한 형', post_text='한티재에서 준비하고 있는 다음 책', post_url='https://f/1')
        self.assertIn('<b>『농부, 짠한 형』 글</b></a> (페이스북)', card(ad))


class MonthLinkTest(TestCase):
    def test_month_items_carry_the_name_and_url_and_lines_stay_plain(self):
        make_ad(book=make_book(), days=[date(2026, 9, 29)], post_url='https://f/1', reach=6000)
        items = ads.month_items(date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual([(i.name, i.url) for i in items],
                         [('', ''), ('『나는 산속으로 더 깊이 들어간다』 글', 'https://f/1')])
        self.assertEqual(ads.month_lines(date(2026, 9, 1), date(2026, 9, 30)), [i.text for i in items])

    def test_monthly_section_links_each_ad_name(self):
        items = [ads.MonthLine('광고 1건 · 광고비 5,000원'),
                 ads.MonthLine('『산속』 글: 1일 · 5,000원', '『산속』 글', 'https://f/1'),
                 ads.MonthLine('외 1건 3,000원')]
        text = monthly._ads_section(items)
        self.assertIn('<b>💸 광고 1건 · 광고비 5,000원</b>', text)
        self.assertIn('· <a href="https://f/1">『산속』 글</a>: 1일 · 5,000원', text)
        self.assertIn('· 외 1건 3,000원', text)

    def test_plain_strings_still_work(self):
        text = monthly._ads_section(['광고 1건 · 광고비 5,000원', '『산속』 글: 1일 · 5,000원'])
        self.assertIn('· 『산속』 글: 1일 · 5,000원', text)
        self.assertNotIn('<a ', text)
