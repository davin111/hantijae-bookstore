from datetime import date

from django.test import TestCase

from books.models import Book, BookAuthor, Category
from intake import mapping

RAINBOW = {
    'title': '무지개를 변호하다', 'subtitle': '트랜스젠더 변호사 박한희의 삶과 생각',
    'authors': [{'name': '박한희', 'role': '지은이'}], 'series': None, 'series_number': None,
    'category': '에세이', 'size': '130×200', 'page_count': 264, 'price': '22,000원',
    'isbn': '979-11-92455-87-7', 'isbn_addon': '03300', 'published_date': '2026년 6월 1일',
    'short_description': '요약', 'description': '서평',
}


class HelpersTest(TestCase):
    def test_isbn(self):
        self.assertTrue(mapping.isbn13_valid('9791192455877'))
        self.assertFalse(mapping.isbn13_valid('9791192455878'))
        self.assertEqual(mapping.format_isbn('979-11-92455-87-7 03300'), '979-11-92455-87-7')
        self.assertEqual(mapping.format_isbn('9791192455754'), '9791192455754')
        self.assertIsNone(mapping.format_isbn('979-11-92455-87-8'))
        self.assertEqual(mapping.isbn_digits('979-11-92455-87-7 03300'), '9791192455877')

    def test_size_price_date_keys(self):
        self.assertEqual(mapping.normalize_size('130×200 무선'), '130*200')
        self.assertEqual(mapping.normalize_size('152*223'), '152*223')
        self.assertEqual(mapping.to_int('22,000원'), 22000)
        self.assertEqual(mapping.parse_date('2026년 6월 1일'), date(2026, 6, 1))
        self.assertEqual(mapping.parse_date('2026-06-01'), date(2026, 6, 1))
        self.assertEqual(mapping.match_name('한티재 팸플릿', {'팸플릿': 2, '시선': 1}), 2)
        self.assertEqual(mapping.match_name('한티재 시선', {'팸플릿': 2, '시선': 1}), 1)


class NormalizeTest(TestCase):
    def test_full_extraction(self):
        n = mapping.normalize_extraction(RAINBOW, {'에세이': 6}, {'단행본': 5})
        self.assertEqual(n.fields['full_price'], 22000)
        self.assertEqual(n.fields['size'], '130*200')
        self.assertEqual(n.fields['category_id'], 6)
        self.assertEqual(n.fields['aladin_url'], 'https://www.aladin.co.kr/search/wsearchresult.aspx?SearchWord=9791192455877')
        self.assertEqual(n.authors, [('박한희', BookAuthor.NORMAL)])
        self.assertEqual((n.unresolved, n.isbn_addon), ([], '03300'))

    def test_missing_and_out_of_range_values_are_unresolved(self):
        data = dict(RAINBOW, price=120000, isbn=None, category='없는 분야', series='한티재 팸플릿', series_number='028')
        n = mapping.normalize_extraction(data, {'에세이': 6}, {'팸플릿': 2})
        self.assertEqual(sorted(n.unresolved), ['category', 'full_price', 'isbn'])
        self.assertEqual((n.series_id, n.series_index), (2, '028'))

    def test_unknown_series_leaves_admin_note(self):
        n = mapping.normalize_extraction(dict(RAINBOW, series='새 시리즈'), {'에세이': 6}, {'단행본': 5})
        self.assertIsNone(n.series_id)
        self.assertEqual(n.notes[0]['audience'], 'admin')


class CheckBookTest(TestCase):
    def setUp(self):
        self.cat = Category.objects.create(name='에세이')

    def make(self, **kw):
        base = dict(title='책', full_price=22000, page_count=264, size='130*200', category=self.cat,
                    published_date=date(2026, 6, 1), isbn='979-11-92455-87-7', is_published=False,
                    short_description='한국 최초로', description='커밍아웃한 변호사')
        base.update(kw)
        return Book.objects.create(**base)

    def codes(self, ws, blocking=None):
        return {w['code'] for w in ws if blocking is None or w['blocking'] == blocking}

    def test_duplicate_isbn_across_formats_is_blocking(self):
        Book.objects.create(title='기존', full_price=1, page_count=1, category=self.cat,
                            published_date=date(2026, 1, 1), isbn='9791192455877')
        ws = mapping.check_book(self.make(), [], [], '한국 최초로 커밍아웃한 변호사', 0.9)
        self.assertIn('isbn_duplicate', self.codes(ws, blocking=True))

    def test_missing_cover_and_unresolved_are_blocking(self):
        ws = mapping.check_book(self.make(), ['full_price'], [], '', 0.9)
        self.assertTrue({'missing:full_price', 'no_front_cover'} <= self.codes(ws, blocking=True))

    def test_verbatim_skips_edited_fields_and_low_quality(self):
        book = self.make(description='바뀐 문장')
        self.assertIn('verbatim:description', self.codes(mapping.check_book(book, [], [], '한국 최초로 커밍아웃한 변호사', 0.9)))
        self.assertNotIn('verbatim:description',
                         self.codes(mapping.check_book(book, [], ['description'], '한국 최초로 커밍아웃한 변호사', 0.9)))
        self.assertIn('verbatim_unchecked', self.codes(mapping.check_book(book, [], [], '', 0.2)))
