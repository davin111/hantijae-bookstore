from datetime import date

from django.test import SimpleTestCase, TestCase

from marketing.selection_match import isbn13, match_books, our_books
from marketing.tests.fakes import make_book


class Isbn13Test(SimpleTestCase):
    def test_strips_hyphens_and_add_on_code(self):
        self.assertEqual(isbn13('978-89-964413-1-1  03810'), '9788996441311')

    def test_rejects_empty_or_short(self):
        self.assertEqual([isbn13(''), isbn13(None), isbn13('89-964413-1-1')], ['', '', ''])


class MatchTest(TestCase):
    def setUp(self):
        self.mugung = make_book(title='무궁화호를 위하여', published=date(2026, 3, 16),
                                isbn='979-11-92455-80-8  03300', author='하승우')
        self.wind = make_book(title='너도바람꽃', published=date(2019, 5, 1), isbn='979-11-00000-01-1', author='조재형')
        self.short = make_book(title='시월', published=date(2020, 1, 1), isbn='979-11-00000-02-8', author='김시월')

    def hits(self, *texts):
        return [(h.book.title, h.how) for h in match_books(list(texts), our_books())]

    def test_isbn_split_by_spaces_or_hyphens_still_matches(self):
        self.assertEqual(self.hits('12 다른 제목 979-11-924558\n08 어느출판사'), [('무궁화호를 위하여', 'isbn')])

    def test_title_with_author_matches_across_line_breaks(self):
        self.assertEqual(self.hits('7 너도바람\n꽃 조재형 아무출판사'), [('너도바람꽃', 'title')])

    def test_title_with_publisher_name_matches(self):
        self.assertEqual(self.hits('너도바람꽃 누군가 도서출판 한티재'), [('너도바람꽃', 'title')])

    def test_title_without_author_or_publisher_does_not_match(self):
        self.assertEqual(self.hits('너도바람꽃 다른저자 다른출판사'), [])

    def test_short_title_never_title_matches(self):
        self.assertEqual(self.hits('시월 김시월 한티재'), [])

    def test_unpublished_books_are_ignored(self):
        make_book(title='비공개 원고', published=date(2026, 1, 1), isbn='979-11-00000-03-5', author='누군가',
                  is_published=False)
        self.assertEqual(self.hits('9791100000035 비공개 원고 누군가 한티재'), [])
