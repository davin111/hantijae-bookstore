from datetime import date, timedelta

from django.test import TestCase

from intake.models import WorkerState
from marketing import bnk, bnk_sales, messages
from marketing.bnk import parse_readers
from marketing.models import BnkSale
from marketing.tests.fakes import FakeBnkClient, make_book, make_sale
from marketing.tests.test_bnk import READERS_JSON

TODAY = date(2026, 9, 30)


def row(isbn, total, title='책', **stores):
    base = {'kyobo': 0, 'yes24': 0, 'aladin': 0, 'ypbooks': 0, 'local': 0}
    return {'isbn': isbn, 'title': title, **base, **stores, 'total': total}


class CollectTest(TestCase):
    def test_first_run_backfills_35_days_then_seven(self):
        c = FakeBnkClient()
        bnk_sales.collect(c, TODAY)
        self.assertEqual((c.asked[0], c.asked[-1], len(c.asked)), (date(2026, 9, 29), date(2026, 8, 26), 35))
        self.assertEqual(WorkerState.get('bnk_backfilled'), '2026-09-30')
        c2 = FakeBnkClient()
        bnk_sales.collect(c2, TODAY + timedelta(days=1))
        self.assertEqual((c2.asked[0], len(c2.asked)), (date(2026, 9, 30), 7))

    def test_day_is_replaced_and_linked_by_isbn13(self):
        WorkerState.put('bnk_backfilled', '2026-09-29')
        book = make_book()   # isbn 979-11-92455-95-2
        make_sale(date(2026, 9, 28), 9, isbn='9791192455999', title='사라진 줄')
        c = FakeBnkClient({date(2026, 9, 28): [row('9791192455952', 3, yes24=2, kyobo=1),
                                               row('9791190178716', 26, title='밥은 먹고 다니냐는 말', yes24=22)]})
        report = bnk_sales.collect(c, TODAY)
        got = {s.isbn: (s.book_id, s.total, s.yes24) for s in BnkSale.objects.filter(day=date(2026, 9, 28))}
        self.assertEqual(got, {'9791192455952': (book.id, 3, 2), '9791190178716': (None, 26, 22)})
        self.assertEqual((report.days, report.rows, report.latest), (7, 2, date(2026, 9, 28)))

    def test_empty_answer_keeps_existing_day(self):
        WorkerState.put('bnk_backfilled', '2026-09-29')
        make_sale(date(2026, 9, 29), 4, isbn='9791192455952')
        bnk_sales.collect(FakeBnkClient(), TODAY)   # 어제는 아직 비어 있다(2일 늦음)
        self.assertEqual(BnkSale.objects.get(day=date(2026, 9, 29)).total, 4)

    def test_failed_day_is_skipped_and_all_failed_raises(self):
        WorkerState.put('bnk_backfilled', '2026-09-29')
        with self.assertLogs('intake', 'WARNING'):
            report = bnk_sales.collect(FakeBnkClient({date(2026, 9, 28): bnk.BnkError('x')}), TODAY)
        self.assertEqual((report.days, report.failed), (6, [date(2026, 9, 28)]))
        every = {TODAY - timedelta(days=i): bnk.BnkError('x') for i in range(1, 8)}
        with self.assertRaises(bnk.BnkError), self.assertLogs('intake', 'WARNING'):
            bnk_sales.collect(FakeBnkClient(every), TODAY)

    def test_login_error_is_not_swallowed(self):
        WorkerState.put('bnk_backfilled', '2026-09-29')
        with self.assertRaises(bnk.BnkLoginError):
            bnk_sales.collect(FakeBnkClient({date(2026, 9, 29): bnk.BnkLoginError('풀림')}), TODAY)

    def test_latest_day_only_within_ten_days(self):
        make_sale(date(2026, 9, 18), 1, isbn='9791192455952')
        self.assertIsNone(bnk_sales.latest_day(TODAY))
        make_sale(date(2026, 9, 25), 1, isbn='9791192455952')
        self.assertEqual(bnk_sales.latest_day(TODAY), date(2026, 9, 25))

    def test_mode_and_report_text(self):
        self.assertEqual(bnk_sales.mode(), 'off')
        text = bnk_sales.report_text(bnk_sales.Report(days=6, rows=12, failed=[date(2026, 9, 28)], latest=date(2026, 9, 27)))
        self.assertEqual(text, '읽은 날 6일 · 판매 줄 12개 · 가장 최근 판매일 2026-09-27 · 못 읽은 날 1일(2026-09-28)')


END = date(2026, 9, 28)


class Books:
    def make(self):
        WorkerState.put('bnk_mode', 'on')
        self.bap = make_book(title='밥은 먹고 다니냐는 말', subtitle='', published=date(2021, 10, 18),
                             isbn='979-11-90178-71-6', author='정은정')
        self.rainbow = make_book(title='무지개를 변호하다', subtitle='', published=date(2026, 6, 1),
                                 isbn='979-11-92455-87-7', author='박한희')


class SalesLineTest(Books, TestCase):
    def setUp(self):
        self.make()
        make_sale(date(2026, 9, 23), 26, book=self.bap, yes24=22, kyobo=1, aladin=2, ypbooks=1)
        make_sale(date(2026, 9, 25), 3, book=self.rainbow, yes24=1, kyobo=1, aladin=1)
        make_sale(date(2026, 9, 16), 20, book=self.bap, yes24=20)
        make_sale(END, 0, isbn='9791192455999', title='오늘 줄')   # 창 끝(가장 최근 판매일) = 9/28

    def test_line(self):
        self.assertEqual(bnk_sales.sales_line(TODAY),
                         '📈 최근 7일(9월 22일~9월 28일) 29권 · 그 전 7일보다 9권 더 · '
                         '가장 많이 팔린 책 『밥은 먹고 다니냐는 말』 26권(예스24 22)')

    def test_less_and_same(self):
        make_sale(date(2026, 9, 17), 20, book=self.rainbow)
        self.assertIn('그 전 7일보다 11권 덜', bnk_sales.sales_line(TODAY))
        BnkSale.objects.filter(day=date(2026, 9, 17)).update(total=9)
        self.assertIn('그 전 7일과 같음', bnk_sales.sales_line(TODAY))

    def test_empty_when_off_or_stale(self):
        WorkerState.put('bnk_mode', 'off')
        self.assertEqual(bnk_sales.sales_line(TODAY), '')
        WorkerState.put('bnk_mode', 'on')
        self.assertEqual(bnk_sales.sales_line(TODAY + timedelta(days=11)), '')

    def test_briefing_text_puts_sales_line_under_the_header(self):
        p = type('P', (), {'headline': '항목', 'reason': '이유', 'extra': {}})()
        text = messages.briefing_text(date(2026, 10, 5), [p], sales='📈 줄')
        self.assertTrue(text.startswith('이번 주 홍보 제안 (10월 5일 ~ 10월 11일)\n\n📈 줄\n\n1. 항목'))
        self.assertNotIn('📈', messages.briefing_text(date(2026, 10, 5), [p]))


class SurgeTest(Books, TestCase):
    def setUp(self):
        self.make()
        self.new = make_book(title='새 책', subtitle='', published=date(2026, 9, 1), isbn='979-11-92455-99-0', author='')
        self.steady = make_book(title='꾸준한 책', subtitle='', published=date(2020, 1, 1), isbn='979-11-92455-98-3',
                                author='')
        make_sale(date(2026, 9, 1), 2, book=self.bap)
        make_sale(date(2026, 9, 16), 2, book=self.bap)
        make_sale(date(2026, 9, 23), 26, book=self.bap, yes24=22, kyobo=1, aladin=2, ypbooks=1)
        make_sale(END, 3, book=self.rainbow)
        make_sale(date(2026, 9, 24), 10, book=self.new)
        make_sale(date(2026, 9, 24), 6, book=self.steady)
        make_sale(date(2026, 9, 10), 20, book=self.steady)

    def test_only_old_books_well_above_usual(self):
        [s] = bnk_sales.surges(TODAY)
        self.assertEqual((s['book'], s['week'], s['usual'], s['end'], s['top']),
                         (self.bap, 26, 1.0, END, ('예스24', 22)))
        self.assertEqual(s['stores'], {'교보': 1, '예스24': 22, '알라딘': 2, '영풍': 1, '지역서점': 0})

    def test_none_when_off(self):
        WorkerState.put('bnk_mode', 'off')
        self.assertIsNone(bnk_sales.surges(TODAY))

    def test_num(self):
        self.assertEqual([bnk_sales.num(x) for x in (0, 0.5, 1.0, 5.25)], ['0', '0.5', '1', '5.2'])


class AroundTest(Books, TestCase):
    def test_two_weeks_before_and_after_posting(self):
        self.make()
        make_sale(date(2026, 9, 1), 2, book=self.bap)
        make_sale(date(2026, 9, 16), 2, book=self.bap)
        make_sale(date(2026, 9, 23), 26, book=self.bap)
        make_sale(END, 1, book=self.rainbow)
        self.assertEqual(bnk_sales.around(self.bap, date(2026, 9, 10), TODAY), (2, 28))
        self.assertIsNone(bnk_sales.around(self.bap, date(2026, 9, 20), TODAY))   # 9/20+13일이 아직 안 들어옴
        WorkerState.put('bnk_mode', 'off')
        self.assertIsNone(bnk_sales.around(self.bap, date(2026, 9, 10), TODAY))


class MonthlyTest(Books, TestCase):
    def setUp(self):
        self.make()
        make_sale(date(2026, 9, 1), 10, book=self.bap, yes24=8, kyobo=2)
        make_sale(date(2026, 9, 23), 26, book=self.bap, yes24=22, kyobo=1, aladin=2, ypbooks=1)
        make_sale(date(2026, 9, 25), 3, book=self.rainbow, kyobo=1, yes24=1, aladin=1)
        make_sale(date(2026, 9, 10), 5, isbn='9791192455999', title='다른 책', local=5)
        make_sale(date(2026, 10, 1), 7, book=self.bap)   # 다음 달은 빼야 한다

    def test_monthly_text(self):
        c = FakeBnkClient(readers=parse_readers(READERS_JSON))
        self.assertEqual(bnk_sales.last_month_start(date(2026, 10, 3)), date(2026, 9, 1))
        self.assertEqual(bnk_sales.monthly_text(c, date(2026, 9, 1)),
                         '📊 9월 판매 요약(전산망)\n'
                         '합계 44권 · 교보 4 · 예스24 31 · 알라딘 3 · 영풍 1 · 지역서점 5\n'
                         '많이 팔린 책: 『밥은 먹고 다니냐는 말』 36권, 『다른 책』 5권, 『무지개를 변호하다』 3권\n'
                         '온라인 구매자: 50대 36% · 40대 16% · 60대 이상 16% / 여성 61% / 경기 54 · 서울 31 · 충북 14')
        self.assertEqual(c.asked, [(date(2026, 9, 1), date(2026, 9, 30))])

    def test_monthly_text_needs_the_whole_month(self):
        BnkSale.objects.filter(day=date(2026, 9, 1)).delete()   # 9/1을 덮는 기록이 없다(처음 켠 달)
        c = FakeBnkClient(readers=parse_readers(READERS_JSON))
        self.assertEqual(bnk_sales.monthly_text(c, date(2026, 9, 1)), '')
        self.assertEqual(c.asked, [])

    def test_status_text(self):
        text = bnk_sales.status_text(date(2026, 10, 2))
        self.assertTrue(text.startswith('bnk_mode=on\nbnk_last_run=None\n가장 최근 판매일=2026-10-01\n최근 7일 합계=10권'))
        self.assertTrue(text.endswith(bnk_sales.USAGE))
