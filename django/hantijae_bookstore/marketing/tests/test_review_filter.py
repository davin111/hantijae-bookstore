from datetime import date

from django.test import TestCase

from books.models import Author, BookAuthor
from marketing.review_filter import excluded, mentions_book, queries, terms
from marketing.review_search import Post
from marketing.tests.fakes import make_book


def post(title, snippet='', url='https://blog.naver.com/a/1'):
    return Post('naver_blog', url, title, snippet, date(2026, 9, 25))


class FilterTest(TestCase):
    def setUp(self):
        self.coming = terms(make_book(title='커밍아웃 스토리', subtitle='성소수자와 그 부모들의 이야기',
                                      published=date(2018, 6, 11), isbn='979-11-00000-01-1', author='성소수자부모모임'))
        self.naeran = terms(make_book(title='내란 앞에서', subtitle='', published=date(2026, 7, 17),
                                      isbn='979-11-00000-02-8', author='김해원'))
        self.long = terms(make_book(title='나는 산속으로 더 깊이 들어간다', subtitle='최정 시집', published=date(2026, 8, 21),
                                    isbn='979-11-00000-03-5', author='최정'))

    def test_full_title_is_required(self):
        self.assertFalse(mentions_book(post('커밍아웃 이야기', '스토리가 있다 한티재'), self.coming))

    def test_short_title_with_author_publisher_or_subtitle_passes(self):
        self.assertTrue(mentions_book(post('커밍아웃 스토리', '성소수자부모모임 2018'), self.coming))
        self.assertTrue(mentions_book(post('커밍아웃 스토리', '한티재에서 나온'), self.coming))
        self.assertTrue(mentions_book(post('커밍아웃 스토리 성소수자와 그 부모들의 이야기'), self.coming))

    def test_short_title_with_a_book_cue_passes(self):
        """2026-09-30 실측에서 스펙 규칙 2(지은이·한티재 필수)가 떨어뜨린 진짜 서평들."""
        self.assertTrue(mentions_book(post('<커밍아웃 스토리>:성소수자와 그 부모 독후감'), self.coming))
        self.assertTrue(mentions_book(post('2023년 10월 모임 후기', '부모모임 <커밍아웃 스토리> 읽기'), self.coming))
        self.assertTrue(mentions_book(post('커밍아웃 스토리', '문득 궁금해서 이 책을 읽게 되었다'), self.coming))

    def test_short_title_in_everyday_talk_is_dropped(self):
        """실측의 잡음: 개인 커밍아웃 이야기, 흔한 말 제목."""
        self.assertFalse(mentions_book(post('나의 커밍아웃 스토리!', '처음 커밍아웃했을 때가 중학교였던 것 같아요'), self.coming))
        self.assertFalse(mentions_book(post('저의 커밍아웃 스토리', '두산팬이었습니다'), self.coming))
        self.assertFalse(mentions_book(post('내란 앞에서 국민은', '헌법재판소 앞에서 시민들이'), self.naeran))

    def test_long_title_alone_is_enough(self):
        self.assertTrue(mentions_book(post('나는 산속으로 더 깊이 들어간다'), self.long))

    def test_official_blog_is_excluded(self):
        self.assertTrue(excluded(post('x', url='https://m.blog.naver.com/hantijae_publisher/224')))
        self.assertFalse(excluded(post('x', url='https://blog.naver.com/reader/224')))

    def test_queries_add_the_first_non_translator(self):
        self.assertEqual(queries(self.naeran), ['"내란 앞에서"', '"내란 앞에서" 김해원'])
        book = make_book(title='퀴어 디플로머시', published=date(2025, 6, 9), isbn='979-11-00000-04-2', author=None)
        BookAuthor.objects.create(book=book, author=Author.objects.create(name='서정현'), author_type=BookAuthor.TRANSLATOR)
        BookAuthor.objects.create(book=book, author=Author.objects.create(name='더글러스 재노프'))
        self.assertEqual(queries(terms(book)), ['"퀴어 디플로머시"', '"퀴어 디플로머시" 더글러스 재노프'])
        lonely = make_book(title='지은이 없는 책', published=date(2020, 1, 1), isbn='979-11-00000-05-9', author=None)
        self.assertEqual(queries(terms(lonely)), ['"지은이 없는 책"'])
