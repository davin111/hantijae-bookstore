from datetime import date
from urllib.parse import parse_qs, urlsplit

from django.test import TestCase

from marketing import loans
from marketing.models import LoanSnapshot
from marketing.tests.fakes import make_book

# 2026-09-30 실제 응답에서 줄인 것
HIT = {'response': {'book': {'bookname': '무궁화호를 위하여 :변경의 현실과 정치', 'loanCnt': 221},
                    'loanHistory': [{'loan': {'month': '2026년 03월', 'loanCnt': 3, 'ranking': 254395}},
                                    {'loan': {'month': '2026년 08월', 'loanCnt': 42, 'ranking': 47106}}],
                    'loanGrps': []}}
MISSING = {'response': {'errCode': 'isbnMpngErr', 'error': 'ISBN에 해당하는 도서가 없습니다.'}}


def no_sleep(_):
    pass


class Api:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __call__(self, url, headers=None):
        isbn = parse_qs(urlsplit(url).query)['isbn13'][0]
        self.calls.append(isbn)
        reply = self.replies[isbn]
        if isinstance(reply, Exception):
            raise reply
        return reply


class LoansTest(TestCase):
    def setUp(self):
        self.mu = make_book(title='무궁화호를 위하여', published=date(2026, 3, 16), isbn='979-11-92455-84-6', author=None)
        self.co = make_book(title='커밍아웃 스토리', published=date(2018, 6, 11), isbn='978-89-97090-88-4 (03810)',
                            author=None)

    def test_parse(self):
        self.assertEqual(loans.parse(HIT), [(date(2026, 3, 1), 3, 254395), (date(2026, 8, 1), 42, 47106)])
        self.assertIsNone(loans.parse(MISSING))
        self.assertEqual(loans.parse_month('2026년 08월'), date(2026, 8, 1))
        with self.assertRaises(ValueError):
            loans.parse({'response': {'errCode': 'authErr', 'error': 'x'}})

    def test_collect_saves_and_overwrites(self):
        api = Api({'9791192455846': HIT, '9788997090884': MISSING})
        report = loans.collect(date(2026, 10, 3), key='k', get_json=api, sleep=no_sleep)
        self.assertEqual((report.books, report.saved, report.missing, report.failed), (2, 2, 1, 0))
        self.assertEqual(sorted(api.calls), ['9788997090884', '9791192455846'])   # 하이픈·부가기호를 뗀 13자리
        s = LoanSnapshot.objects.get(book=self.mu, month=date(2026, 8, 1))
        self.assertEqual((s.loans, s.ranking), (42, 47106))
        api.replies['9791192455846'] = {'response': {'loanHistory': [
            {'loan': {'month': '2026년 08월', 'loanCnt': 45, 'ranking': 45000}}]}}
        loans.collect(date(2026, 10, 10), key='k', get_json=api, sleep=no_sleep)
        self.assertEqual(LoanSnapshot.objects.get(book=self.mu, month=date(2026, 8, 1)).loans, 45)   # 늦게 들어온 대출 반영

    def test_missing_books_are_not_failures(self):
        make_book(title='ISBN 없는 책', published=date(2020, 1, 1), isbn='', author=None)
        api = Api({'9791192455846': MISSING, '9788997090884': MISSING})
        report = loans.collect(date(2026, 10, 3), key='k', get_json=api, sleep=no_sleep)
        self.assertEqual((report.books, report.missing, report.failed), (2, 2, 0))

    def test_failure_never_logs_the_key(self):
        api = Api({'9791192455846': RuntimeError('500 for url http://data4library.kr/api?authKey=SECRETKEY'),
                   '9788997090884': HIT})
        with self.assertLogs('intake', level='WARNING') as cm:
            report = loans.collect(date(2026, 10, 3), key='SECRETKEY', get_json=api, sleep=no_sleep)
        self.assertEqual(report.failed, 1)
        self.assertNotIn('SECRETKEY', '\n'.join(cm.output))

    def test_every_book_failing_raises(self):
        api = Api({'9791192455846': RuntimeError('x'), '9788997090884': RuntimeError('y')})
        with self.assertLogs('intake', level='WARNING'), self.assertRaises(RuntimeError) as ctx:
            loans.collect(date(2026, 10, 3), key='SECRETKEY', get_json=api, sleep=no_sleep)
        self.assertNotIn('SECRETKEY', str(ctx.exception))

    def test_no_key_does_nothing(self):
        api = Api({})
        self.assertEqual(loans.collect(date(2026, 10, 3), key='', get_json=api, sleep=no_sleep).books, 0)
        self.assertEqual(api.calls, [])

    def test_calls_are_spaced(self):
        sleeps = []
        loans.collect(date(2026, 10, 3), key='k', get_json=Api({'9791192455846': MISSING, '9788997090884': MISSING}),
                      sleep=sleeps.append)
        self.assertEqual(sleeps, [loans.SPACING])
