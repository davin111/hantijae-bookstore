from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from web import presenters as p


def book(**kw):
    base = dict(isbn=None, aladin_url='', yes24_url='', kyobo_url='')
    base.update(kw)
    return SimpleNamespace(**base)


class CreditTest(SimpleTestCase):
    def test_credit_line_orders_roles_and_joins(self):
        self.assertEqual(p.credit_line([('김해원', 1), ('헌법공부모임 제1조', 3)]), '김해원 지음 · 헌법공부모임 제1조 기획')
        self.assertEqual(p.credit_line([('해강', 2), ('나카야마 가호', 1)]), '나카야마 가호 지음 · 해강 옮김')
        self.assertEqual(p.credit_line([('A', 1), ('B', 1), ('C', 4)]), 'A, B 지음 · C 엮음')

    def test_credit_line_ignores_unknown_role(self):
        self.assertEqual(p.credit_line([('A', 1), ('X', 9)]), 'A 지음')

    def test_card_credit_first_name_of_first_role(self):
        self.assertEqual(p.card_credit([('해강', 2), ('나카야마 가호', 1)]), '나카야마 가호')
        self.assertEqual(p.card_credit([('A', 1), ('B', 1)]), 'A 외')
        self.assertEqual(p.card_credit([('C', 4)]), 'C')
        self.assertEqual(p.card_credit([]), '')


class FormatTest(SimpleTestCase):
    def test_price_date_month(self):
        self.assertEqual(p.format_price(14000), '14,000원')
        self.assertEqual(p.format_price(None), '')
        self.assertEqual(p.format_date_ko(date(2021, 7, 12)), '2021년 7월 12일')
        self.assertEqual(p.format_month_ko(date(2026, 8, 21)), '2026년 8월')
        self.assertEqual(p.format_date_ko(None), '')

    def test_size(self):
        self.assertEqual(p.format_size('125*188'), '125×188mm')
        self.assertEqual(p.format_size(' 130 x 204 '), '130×204mm')
        self.assertEqual(p.format_size('신국판 변형'), '신국판 변형')
        self.assertEqual(p.format_size('148*210*20'), '148×210×20')
        self.assertEqual(p.format_size(None), '')

    def test_isbn(self):
        self.assertEqual(p.format_isbn('979-11-90178-60-0  04450'), '979-11-90178-60-0 04450')
        self.assertEqual(p.isbn13('979-11-90178-60-0  04450'), '9791190178600')
        self.assertEqual(p.isbn13('9788912345678'), '9788912345678')
        self.assertIsNone(p.isbn13('89-123-4567'))
        self.assertIsNone(p.isbn13(None))


class StoreLinkTest(SimpleTestCase):
    def test_store_links_prefers_saved_and_falls_back_to_isbn_search(self):
        b = book(isbn='979-11-90178-60-0  04450', kyobo_url='https://product.kyobobook.co.kr/detail/S000001')
        links = {l.store: l for l in p.store_links(b)}
        self.assertEqual([l.label for l in p.store_links(b)], ['알라딘', 'YES24', '교보문고'])
        self.assertEqual(links['aladin'].url,
                         'https://www.aladin.co.kr/search/wsearchresult.aspx?SearchTarget=Book&SearchWord=9791190178600')
        self.assertEqual(links['yes24'].url, 'https://www.yes24.com/product/search?domain=ALL&query=9791190178600')
        self.assertEqual(links['kyobo'].url, 'https://product.kyobobook.co.kr/detail/S000001')

    def test_store_links_ignores_expired_url_kr_shortlinks(self):
        b = book(isbn='9791190178600', yes24_url='https://url.kr/abcd12')
        self.assertEqual(p.store_url(b, 'yes24'), 'https://www.yes24.com/product/search?domain=ALL&query=9791190178600')

    def test_store_links_without_isbn_or_saved_urls_is_empty(self):
        self.assertEqual(p.store_links(book()), [])
        self.assertEqual([l.store for l in p.store_links(book(aladin_url='https://aladin.kr/p/X'))], ['aladin'])


class DescriptionTest(SimpleTestCase):
    def test_parse_description_sections_lead_and_collapsible(self):
        text = ('갈릴레이 온도계부터,\n일기예보의 시대\n\n본문 첫 문단입니다.\n​\n'
                '■ 저자 소개\n김해동\n\n약력\n■ 차례​\n1장\n2장')
        sections = p.parse_description(text)
        self.assertEqual([s.title for s in sections], ['책 소개', '저자 소개', '차례'])
        self.assertEqual([s.anchor for s in sections], ['section-1', 'section-2', 'section-3'])
        self.assertEqual(sections[0].lead, '갈릴레이 온도계부터,<br>일기예보의 시대')
        self.assertEqual(sections[0].paragraphs, ['본문 첫 문단입니다.'])
        self.assertEqual(sections[1].paragraphs, ['김해동', '약력'])
        self.assertTrue(sections[2].collapsible)
        self.assertEqual(sections[2].paragraphs, ['1장<br>2장'])

    def test_parse_description_without_headings_is_single_untitled_section(self):
        sections = p.parse_description('첫 줄\n\n둘째 문단')
        self.assertEqual(len(sections), 1)
        self.assertIsNone(sections[0].title)

    def test_parse_description_escapes_html(self):
        long = '가' * 130
        sections = p.parse_description(f'{long}\n\n<script>alert(1)</script> **굵게**')
        self.assertIsNone(sections[0].lead)
        self.assertEqual(sections[0].paragraphs[1], '&lt;script&gt;alert(1)&lt;/script&gt; <strong>굵게</strong>')

    def test_heading_trailing_dashes_and_empty_sections(self):
        sections = p.parse_description('■ 한티재 교양문고 ---------\n소개글\n■ 빈 구획\n')
        self.assertEqual([s.title for s in sections], ['한티재 교양문고'])
        self.assertEqual(p.parse_description(''), [])

    def test_strip_marks_and_short_text(self):
        self.assertEqual(p.strip_marks('**도시** 생활'), '도시 생활')
        self.assertEqual(p.short_text('가나다라마 바사', 5), '가나다라…')
        self.assertEqual(p.short_text('짧다', 5), '짧다')
