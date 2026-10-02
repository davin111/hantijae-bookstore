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

    def test_store_links_ignore_third_party_shortlinks(self):
        # bit.ly 는 브라우저에 7초 미리보기 페이지를, kyobo.link 는 도메인이 없어 열리지 않는다(2026-09-29 확인)
        b = book(isbn='9791190178600', aladin_url='https://bit.ly/3ed373l', kyobo_url='http://kyobo.link/g2h0',
                 yes24_url='https://BIT.LY/abc')
        self.assertEqual(p.store_url(b, 'aladin'),
                         'https://www.aladin.co.kr/search/wsearchresult.aspx?SearchTarget=Book&SearchWord=9791190178600')
        self.assertEqual(p.store_url(b, 'kyobo'),
                         'https://search.kyobobook.co.kr/search?keyword=9791190178600&gbCode=TOT&target=total')
        self.assertEqual(p.store_url(b, 'yes24'), 'https://www.yes24.com/product/search?domain=ALL&query=9791190178600')

    def test_store_links_keep_store_owned_shortlinks(self):
        # aladin.kr 은 알라딘이 직접 운영하는 단축 주소라 바로 상품 페이지로 간다
        self.assertEqual(p.store_url(book(aladin_url='http://aladin.kr/p/Pybh6'), 'aladin'), 'http://aladin.kr/p/Pybh6')

    def test_store_links_without_isbn_or_saved_urls_is_empty(self):
        self.assertEqual(p.store_links(book()), [])
        self.assertEqual([l.store for l in p.store_links(book(aladin_url='https://aladin.kr/p/X'))], ['aladin'])


def ebook(**kw):
    base = dict(ebook_isbn='', ebook_aladin_url='', ebook_yes24_url='', ebook_kyobo_url='', ebook_ridi_url='')
    base.update(kw)
    return SimpleNamespace(**base)


class EbookLinkTest(SimpleTestCase):
    def test_saved_urls_in_store_order(self):
        b = ebook(ebook_ridi_url='https://ridibooks.com/books/754042189',
                  ebook_yes24_url='https://www.yes24.com/product/goods/128200636')
        self.assertEqual([(l.store, l.label) for l in p.ebook_links(b)], [('e_yes24', 'YES24'), ('ridi', '리디')])

    def test_isbn_search_only_where_it_reaches_the_ebook(self):
        # 예스24 검색 주소는 쿠키 없는 데스크톱 첫 방문자를 첫 화면으로 보내고, 리디 검색은 화면을 스크립트로 그린다(2026-10-02)
        links = {l.store: l.url for l in p.ebook_links(ebook(ebook_isbn='979-11-92455-47-1'))}
        self.assertEqual(links, {
            'e_aladin': 'https://www.aladin.co.kr/search/wsearchresult.aspx?SearchTarget=eBook&SearchWord=9791192455471',
            'e_kyobo': 'https://search.kyobobook.co.kr/search?keyword=9791192455471&gbCode=TOT&target=total'})

    def test_no_ebook_data_means_no_links(self):
        self.assertEqual(p.ebook_links(ebook()), [])
        self.assertEqual(p.ebook_links(ebook(ebook_aladin_url='https://bit.ly/x')), [])

    def test_link_url_covers_paper_and_ebook_stores(self):
        b = SimpleNamespace(**vars(book(isbn='9791190178600')), **vars(ebook(ebook_ridi_url='https://ridibooks.com/books/1')))
        self.assertEqual(p.link_url(b, 'ridi'), 'https://ridibooks.com/books/1')
        self.assertTrue(p.link_url(b, 'aladin').endswith('SearchWord=9791190178600'))
        self.assertIsNone(p.link_url(b, 'e_yes24'))
        self.assertIsNone(p.link_url(b, 'amazon'))


class CoverUrlTest(SimpleTestCase):
    def test_cover_card_url_prefers_thumbnail(self):
        f = lambda url: SimpleNamespace(url=url) if url else None  # noqa: E731
        b = SimpleNamespace(cover_thumbnail=f('/t.jpg'), cover_image=f('/c.png'), cover_image_3d=None)
        self.assertEqual(p.cover_card_url(b), '/t.jpg')
        b.cover_thumbnail = None
        self.assertEqual(p.cover_card_url(b), '/c.png')
        self.assertEqual(p.cover_3d_url(b), '/c.png')


def series(name):
    return SimpleNamespace(name=name)


class SeriesNameTest(SimpleTestCase):
    def test_official_name_has_hantijae_prefix_except_danhaengbon(self):
        self.assertEqual(p.series_name(series('시의숲')), '한티재 시의숲')
        self.assertEqual(p.series_name(series('교양문고')), '한티재 교양문고')
        self.assertEqual(p.series_name(series('단행본')), '단행본')

    def test_menu_name_is_short(self):
        self.assertEqual(p.series_menu_name(series('팸플릿')), '팸플릿')
        self.assertEqual(p.series_menu_name(series('시선')), '시선')

    def test_series_number_padded_by_series_rule(self):
        self.assertEqual(p.series_number(series('교양문고'), '001'), '01')
        self.assertEqual(p.series_number(series('산문선'), '4'), '04')
        self.assertEqual(p.series_number(series('팸플릿'), '27'), '027')
        self.assertEqual(p.series_number(series('시선'), ' 023 '), '023')
        self.assertEqual(p.series_number(series('팸플릿'), '특별판'), '특별판')   # 숫자가 아니면 그대로

    def test_series_without_numbers_shows_none(self):
        self.assertEqual(p.series_number(series('시의숲'), '01'), '')
        self.assertEqual(p.series_number(series('단행본'), None), '')
        self.assertEqual(p.series_number(series('시선'), None), '')

    def test_series_label_joins_official_name_and_number(self):
        self.assertEqual(p.series_label(series('시선'), '23'), '한티재 시선 023')
        self.assertEqual(p.series_label(series('시의숲'), '01'), '한티재 시의숲')
        self.assertEqual(p.series_label(series('단행본'), None), '단행본')


def texts(section):
    return [x.html for x in section.paragraphs]


def marked(section):
    return [(x.html, x.subhead) for x in section.paragraphs]


# 리드(120자 이하 첫 문단)로 빠지지 않을 만큼 긴 본문 문단
BODY = ' '.join(['시인은 골짝 밖으로 나가 산불감시원 일을 시작했다.'] * 5)


class DescriptionTest(SimpleTestCase):
    def test_parse_description_sections_lead_and_collapsible(self):
        text = ('갈릴레이 온도계부터,\n일기예보의 시대\n\n본문 첫 문단입니다.\n​\n'
                '■ 저자 소개\n김해동\n\n약력\n■ 차례​\n1장\n2장')
        sections = p.parse_description(text)
        self.assertEqual([s.title for s in sections], ['책 소개', '저자 소개', '차례'])
        self.assertEqual([s.anchor for s in sections], ['section-1', 'section-2', 'section-3'])
        self.assertEqual(sections[0].lead, '갈릴레이 온도계부터,<br>일기예보의 시대')
        self.assertEqual(texts(sections[0]), ['본문 첫 문단입니다.'])
        self.assertEqual(texts(sections[1]), ['김해동', '약력'])
        self.assertTrue(sections[2].collapsible)
        self.assertEqual(texts(sections[2]), ['1장<br>2장'])

    def test_short_line_followed_by_body_is_subhead(self):
        text = (f'시집 출간\n\n{BODY}\n\n몸을 통과한 흙과 노동의 언어\n\n{BODY}\n\n'
                '풀과 나무, 지구를 향한 상상력\n\n2부와 3부에는 이웃 이야기가 담겨 있다.')
        section = p.parse_description(text)[0]
        self.assertEqual(section.lead, '시집 출간')   # 첫 짧은 문단은 소제목이 아니라 리드
        self.assertEqual(marked(section), [
            (BODY, False), ('몸을 통과한 흙과 노동의 언어', True), (BODY, False),
            ('풀과 나무, 지구를 향한 상상력', True), ('2부와 3부에는 이웃 이야기가 담겨 있다.', False)])

    def test_two_short_lines_before_body_make_one_subhead(self):
        text = f'{BODY}\n\n캐나다 외교관이 기록한\n\n성소수자 인권 외교의 현황과 과제\n\n{BODY}'
        self.assertEqual(marked(p.parse_description(text)[0]), [
            (BODY, False), ('캐나다 외교관이 기록한<br>성소수자 인권 외교의 현황과 과제', True), (BODY, False)])

    def test_short_lines_that_are_not_subheads(self):
        verse = '아무도 중심에 서지 않아\n\n새로운 것은 자잘한 데서 오는 법\n\n모두가 둘레를 자청하고 살지'
        text = (f'{BODY}\n\n{verse}\n\n{BODY}\n\n이 책은 좋은 지침서가 될 것이다\n\n{BODY}\n\n'
                f'“따옴표로 여는 인용\n\n{BODY}\n\n뒤에 본문이 없는 줄')
        self.assertFalse(any(x.subhead for x in p.parse_description(text)[0].paragraphs))

    def test_contact_toc_and_credit_lines_are_not_subheads(self):
        # 옛 책 소개에 섞인 연락처·쪽수 붙은 차례·글쓴이 표기·추천사 출처 줄(운영 데이터에서 본 모양)
        for line in ('verticalkjh@naver.com', '005책머리에', '책을 펴내며 _ 안수진', '닫는 글_  21세기 지역 인문학',
                     '발문 | 질병의 시대에 건네는 생명의 목소리 | 김연주', '이희인 (『여행자의 독서』 저자), 추천사'):
            with self.subTest(line=line):
                self.assertFalse(p.parse_description(f'{BODY}\n\n{line}\n\n{BODY}')[0].paragraphs[1].subhead)
        # 숫자로 시작해도 쪽수가 아니면 소제목
        self.assertTrue(p.parse_description(f'{BODY}\n\n150년이 지나서도 유효한 사상\n\n{BODY}')[0].paragraphs[1].subhead)

    def test_subheads_skip_toc_and_excerpt_sections(self):
        text = (f'{BODY}\n■ 본문 중에서\n꽃밭에서\n\n{BODY}\n■ 차례\n1부 첫 이야기\n\n{BODY}\n'
                f'■ 저자 소개\n김해동\n\n{BODY}')
        sections = {s.title: s for s in p.parse_description(text)}
        self.assertFalse(any(x.subhead for x in sections['본문 중에서'].paragraphs))
        self.assertFalse(any(x.subhead for x in sections['차례'].paragraphs))
        self.assertTrue(sections['저자 소개'].paragraphs[0].subhead)   # 약력 앞 이름 줄

    def test_parse_description_without_headings_is_single_untitled_section(self):
        sections = p.parse_description('첫 줄\n\n둘째 문단')
        self.assertEqual(len(sections), 1)
        self.assertIsNone(sections[0].title)

    def test_parse_description_escapes_html(self):
        long = '가' * 130
        sections = p.parse_description(f'{long}\n\n<script>alert(1)</script> **굵게**')
        self.assertIsNone(sections[0].lead)
        self.assertEqual(texts(sections[0])[1], '&lt;script&gt;alert(1)&lt;/script&gt; <strong>굵게</strong>')

    def test_heading_trailing_dashes_and_empty_sections(self):
        sections = p.parse_description('■ 한티재 교양문고 ---------\n소개글\n■ 빈 구획\n')
        self.assertEqual([s.title for s in sections], ['한티재 교양문고'])
        self.assertEqual(p.parse_description(''), [])

    def test_strip_marks_and_short_text(self):
        self.assertEqual(p.strip_marks('**도시** 생활'), '도시 생활')
        self.assertEqual(p.short_text('가나다라마 바사', 5), '가나다라…')
        self.assertEqual(p.short_text('짧다', 5), '짧다')
