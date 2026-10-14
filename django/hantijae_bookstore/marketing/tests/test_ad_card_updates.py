from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from intake.models import WorkerState
from marketing import ads, ad_cards
from marketing.models import Ad, AdDay, BnkDay
from marketing.tests.fakes import FakeTG, make_ad, make_book
from marketing.tests.test_ads import at


class CardUpdateTest(TestCase):
    def setUp(self):
        WorkerState.put('ads_card_mode', 'live')
        WorkerState.put('bnk_mode', 'off')
        self.tg = FakeTG()
        self.bot = SimpleNamespace(tg=self.tg, marketing=SimpleNamespace(mode=lambda: 'live'),
                                   review_chat_id=lambda: -200, _chat=lambda kind: 100)
        self.fetch = lambda *a: {'facebook': [], 'instagram': []}

    def ad(self, ad_id='1'):
        return make_ad(ad_id=ad_id, days=[date(2026, 9, 28)], spend=5000, reach=800, link_clicks=10,
                       book_title='같은 제목', post_text='글 ' + ad_id, totals_at=at(10, 1, 7))

    def run_cards(self, when):
        WorkerState.put('ads_ok_on', when.date().isoformat())
        return ads.send_due_cards(self.bot, when, fetch=self.fetch)

    def extend(self, ad, end=date(2026, 10, 11), fresh=None):
        ad.refresh_from_db()
        AdDay.objects.create(ad=ad, day=end, spend=7000)
        ad.last_day, ad.spend, ad.reach, ad.link_clicks = end, 12000, 1500, 25
        ad.totals_at = fresh or at(10, 14, 7)
        ad.save()

    def records(self):
        return list(WorkerState.objects.filter(key__startswith='ads_card_message_'))

    def test_card_distinguishes_source_from_performance_scope(self):
        self.ad()
        self.run_cards(at(10, 1))
        body = self.tg.sent('send')[0]['text']
        self.assertIn('(원본 글: 페이스북)', body)
        self.assertIn('성과는 모든 게재 위치 합계', body)

    def test_send_saves_message_and_reported_range(self):
        ad = self.ad()
        self.run_cards(at(10, 1))
        self.assertEqual(len(self.records()), 1)
        record = self.records()[0].value
        self.assertEqual((record['chat_id'], record['message_id']), (-200, 1001))
        self.assertEqual(record['ads'], [{'id': ad.pk, 'last_day': '2026-09-28', 'spend': 5000}])

    def test_ended_extension_edits_same_card_once_and_preserves_other_ad_and_notes(self):
        ad, other = self.ad(), self.ad('2')
        self.run_cards(at(10, 1))
        if self.records():
            record = self.records()[0]
            record.value['notes'] = '추가 확인: 숫자는 구매 인원이 아닙니다.'
            record.save()
        self.extend(ad)
        self.assertEqual(self.run_cards(at(10, 14)), 1)
        self.assertEqual(len(self.tg.sent('send')), 1)
        [edit] = self.tg.sent('edit')
        self.assertEqual((edit['chat'], edit['message_id']), (-200, 1001))
        for part in ('12,000원', '5,000원', '추가 확인:', '연장 집행을 포함한 누적 결과'):
            self.assertIn(part, edit['text'])
        self.assertEqual(self.run_cards(at(10, 14, 15)), 0)
        self.assertEqual(len(self.tg.sent('edit')), 1)
        other.refresh_from_db()
        self.assertEqual(other.card, Ad.SENT)

    def test_active_extension_and_stale_totals_wait(self):
        ad = self.ad()
        self.run_cards(at(10, 1))
        self.extend(ad, date(2026, 10, 13))
        self.assertEqual(self.run_cards(at(10, 14)), 0)
        self.assertEqual(self.run_cards(at(10, 16)), 0)  # today's collection alone isn't fresh ad totals
        ad.totals_at = at(10, 16, 7)
        ad.save()
        self.assertEqual(self.run_cards(at(10, 16)), 1)
        self.assertEqual(len(self.tg.sent('send')), 1)

    def test_old_untracked_sent_ad_is_never_resent(self):
        ad = self.ad()
        ad.card, ad.card_sent_at = Ad.SENT, at(10, 1)
        ad.save()
        self.extend(ad)
        self.assertEqual(self.run_cards(at(10, 14)), 0)
        self.assertEqual(self.tg.calls, [])

    def test_same_title_new_ad_is_a_new_card(self):
        self.ad()
        self.run_cards(at(10, 1))
        other = self.ad('2')
        self.assertEqual(self.run_cards(at(10, 2)), 1)
        self.assertEqual(len(self.tg.sent('send')), 2)
        self.assertEqual(self.tg.sent('edit'), [])

    def test_off_or_changed_target_does_not_edit_old_group_card(self):
        ad = self.ad()
        self.run_cards(at(10, 1))
        self.extend(ad)
        for mode in ('off', 'admin_only'):
            WorkerState.put('ads_card_mode', mode)
            self.assertEqual(self.run_cards(at(10, 14)), 0)
        WorkerState.put('ads_card_mode', 'live')
        self.assertEqual(self.run_cards(at(10, 14)), 1)

    def test_failed_edit_retries_same_message_after_thirty_minutes(self):
        ad = self.ad()
        self.run_cards(at(10, 1))
        self.extend(ad)
        original = self.tg.edit_text
        def fail(*a, **kw):
            raise RuntimeError('telegram down')
        self.tg.edit_text = fail
        with self.assertRaises(RuntimeError):
            self.run_cards(at(10, 14, 10, 0))
        self.assertEqual(self.records()[0].value['ads'][0]['last_day'], '2026-09-28')
        self.tg.edit_text = original
        self.assertEqual(self.run_cards(at(10, 14, 10, 10)), 0)
        self.assertEqual(self.run_cards(at(10, 14, 10, 31)), 1)
        self.assertEqual(len(self.tg.sent('send')), 1)

    def test_new_card_daily_limit_does_not_block_extension_edit(self):
        ad = self.ad()
        self.run_cards(at(10, 1))
        self.extend(ad)
        WorkerState.put('ads_card_day', '2026-10-14')
        self.assertEqual(self.run_cards(at(10, 14)), 1)
        self.assertEqual(len(self.tg.sent('edit')), 1)

    def test_missing_member_of_grouped_card_blocks_edit(self):
        ad, other = self.ad(), self.ad('2')
        self.run_cards(at(10, 1))
        other.delete()
        self.extend(ad)
        self.assertEqual(self.run_cards(at(10, 14)), 0)
        self.assertEqual(self.tg.sent('edit'), [])

    def test_oversize_notes_fail_before_telegram_instead_of_truncating(self):
        ad = self.ad()
        self.run_cards(at(10, 1))
        if self.records():
            record = self.records()[0]
            record.value['notes'] = '설명' * 2200
            record.save()
        self.extend(ad)
        with self.assertRaises(ValueError):
            self.run_cards(at(10, 14))
        self.assertEqual(self.tg.sent('edit'), [])



class CardSalesAndRecoveryTest(TestCase):
    def setUp(self):
        WorkerState.put('ads_card_mode', 'live')
        WorkerState.put('bnk_mode', 'off')
        self.tg = FakeTG()
        self.bot = SimpleNamespace(tg=self.tg, marketing=SimpleNamespace(mode=lambda: 'live'),
                                   review_chat_id=lambda: -200, _chat=lambda kind: 100)
        self.fetch = lambda *a: {'facebook': [], 'instagram': []}

    def run_cards(self, when):
        WorkerState.put('ads_ok_on', when.date().isoformat())
        return ads.send_due_cards(self.bot, when, fetch=self.fetch)

    def ad(self, ad_id='1', days=None, book=None):
        return make_ad(ad_id=ad_id, days=days or [date(2026, 9, 28)], book=book,
                       spend=5000, reach=800, totals_at=at(10, 1, 7))

    def extend(self, ad, end=date(2026, 10, 11)):
        ad.refresh_from_db()
        AdDay.objects.create(ad=ad, day=end, spend=7000)
        ad.last_day, ad.spend, ad.totals_at = end, 12000, at(10, 14, 7)
        ad.save()

    def sales_days(self, first, last):
        while first <= last:
            BnkDay.objects.get_or_create(day=first, defaults={'read_on': first + timedelta(days=2)})
            first += timedelta(days=1)

    def test_single_extension_waits_for_sales_ready(self):
        book = make_book()
        ad = self.ad(book=book)
        self.run_cards(at(10, 1))
        self.extend(ad)
        WorkerState.put('bnk_mode', 'on')
        self.sales_days(date(2026, 8, 1), date(2026, 10, 10))
        self.assertEqual(self.run_cards(at(10, 14)), 0)
        self.sales_days(date(2026, 10, 11), date(2026, 10, 11))
        self.assertEqual(self.run_cards(at(10, 14)), 1)

    def test_both_extensions_wait_until_all_are_ended(self):
        first, second = self.ad(), self.ad('2')
        self.run_cards(at(10, 1))
        self.extend(first)
        self.extend(second, date(2026, 10, 13))
        self.assertEqual(self.run_cards(at(10, 14)), 0)
        self.assertEqual(self.tg.sent('edit'), [])

    def test_edit_db_failure_retries_same_message(self):
        ad = self.ad()
        self.run_cards(at(10, 1))
        self.extend(ad)
        original_put = WorkerState.put

        def fail_after_edit(key, value):
            if key.startswith(ad_cards.PREFIX) and value['ads'][0]['last_day'] == '2026-10-11':
                raise RuntimeError('simulated state write failure')
            return original_put(key, value)

        with patch.object(WorkerState, 'put', side_effect=fail_after_edit):
            with self.assertRaises(RuntimeError):
                self.run_cards(at(10, 14, 10, 0))
        self.assertEqual(self.run_cards(at(10, 14, 10, 10)), 0)
        self.assertEqual(self.run_cards(at(10, 14, 10, 30)), 1)
        self.assertEqual([edit['message_id'] for edit in self.tg.sent('edit')], [1001, 1001])
        self.assertEqual(len(self.tg.sent('send')), 1)

    def test_group_extension_waits_for_rendered_sales_range(self):
        """같은 책 묶음의 합쳐진 판매 비교 기간도 준비된 다음에 갱신해야 한다."""
        WorkerState.put('bnk_mode', 'on')
        book = make_book()
        self.sales_days(date(2026, 8, 1), date(2026, 8, 1))
        self.sales_days(date(2026, 9, 1), date(2026, 9, 28))
        self.ad('1', days=[date(2026, 9, 20), date(2026, 9, 27)], book=book)
        extended = self.ad('2', book=book)
        self.assertEqual(self.run_cards(at(10, 1)), 1)
        self.assertIn('전산망 판매', self.tg.sent('send')[0]['text'])
        self.extend(extended)
        self.sales_days(date(2026, 9, 29), date(2026, 10, 11))
        # extended 혼자의 비교 시작일은 9/14라 준비됨. 실제 카드의 합쳐진
        # 비교 시작일은 8/29라 8/29~31이 아직 비어 있음.
        self.assertTrue(ads._ready(extended, date(2026, 10, 14)))
        self.assertIsNone(ads.sales_around(book, date(2026, 9, 20), date(2026, 10, 11)))
        self.assertEqual(self.run_cards(at(10, 14)), 0)
        self.assertEqual(self.tg.sent('edit'), [])

        self.sales_days(date(2026, 8, 29), date(2026, 8, 31))
        self.assertEqual(self.run_cards(at(10, 14)), 1)
        self.assertIn('광고 전 22일 0권 → 광고 22일 0권', self.tg.sent('edit')[0]['text'])
