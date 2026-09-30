from datetime import date, timedelta

from django.test import TestCase

from intake.models import WorkerState
from marketing import bnk, bnk_sales
from marketing.models import BnkSale
from marketing.tests.fakes import FakeBnkClient, make_book, make_sale

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
