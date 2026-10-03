from datetime import date, datetime, timedelta

from django.test import TestCase

from intake.models import WorkerState
from marketing.models import Briefing, SalesSnapshot, Signal
from marketing.tests.fakes import make_book
from marketing.timeutil import KST
from ops import health


def kst(*args):
    return datetime(*args, tzinfo=KST)


def put(**values):
    for k, v in values.items():
        WorkerState.put(k, v)


class HealthTest(TestCase):
    NOW = kst(2026, 10, 3, 11, 18)   # 토요일, 자동화 지도 스냅샷 시각

    def setUp(self):
        put(marketing_mode='live')

    def rows(self, now=None):
        return {r.key: r for r in health.evaluate(now or self.NOW)}

    # ---- 매일 작업: 돌았나 · 실패 근거 · 새 기록 ----

    def test_daily_task_that_ran_with_new_rows_is_ok(self):
        book = make_book()
        SalesSnapshot.objects.create(book=book, date=date(2026, 10, 3), sales_point=7307)
        put(marketing_last_sales_scan='2026-10-03', marketing_sales_fail_streak=0)
        self.assertEqual(self.rows()['sales'].state, health.OK)

    def test_review_that_ran_without_new_reviews_is_calm_and_with_one_is_ok(self):
        put(marketing_last_review_scan='2026-10-03')
        self.assertEqual(self.rows()['review'].state, health.CALM)
        Signal.objects.create(kind=Signal.REVIEW, key='review:1', title='서평', found_at=kst(2026, 10, 3, 4, 35),
                              detail={'source': 'naver_blog', 'verdict': 'review'})
        self.assertEqual(self.rows()['review'].state, health.OK)

    def test_baseline_posts_are_not_counted_as_reviews(self):
        put(marketing_last_review_scan='2026-10-03')
        Signal.objects.create(kind=Signal.REVIEW, key='review:2', title='옛 글', found_at=kst(2026, 10, 3, 4, 35),
                              detail={'source': 'naver_blog', 'verdict': 'old'})
        self.assertEqual(self.rows()['review'].state, health.CALM)

    def test_daily_task_is_late_only_after_the_grace_period(self):
        put(marketing_last_review_scan='2026-10-02')
        self.assertNotEqual(self.rows(kst(2026, 10, 3, 5, 29))['review'].state, health.WARN)
        late = self.rows(kst(2026, 10, 3, 5, 31))['review']
        self.assertEqual(late.state, health.WARN)
        self.assertIn('04:30', late.reason)

    def test_fail_counter_makes_it_worth_a_look(self):
        put(marketing_last_review_scan='2026-10-03', review_fail_naver_blog=2)
        row = self.rows()['review']
        self.assertEqual(row.state, health.WARN)
        self.assertIn('review_fail_naver_blog', row.reason)

    def test_recent_marketing_error_key_makes_it_worth_a_look_but_old_one_does_not(self):
        put(marketing_last_selection_scan='2026-10-03', marketing_error_selection='2026-10-03')
        self.assertEqual(self.rows()['selection'].state, health.WARN)
        put(marketing_error_selection='2026-09-29')
        self.assertNotEqual(self.rows()['selection'].state, health.WARN)

    def test_error_key_without_its_own_row_still_shows_up(self):
        put(marketing_error_run_due='2026-10-03')
        warn = health.watch(health.evaluate(self.NOW))
        self.assertTrue(any('marketing_error_run_due' in r.reason for r in warn))

    def test_switched_off_tasks_are_off_and_not_worth_a_look(self):
        put(marketing_mode='off', marketing_last_review_scan='2026-09-01')
        row = self.rows()['review']
        self.assertEqual(row.state, health.OFF)
        self.assertNotIn(row, health.watch(health.evaluate(self.NOW)))

    # ---- 매주·매달 작업 ----

    def test_weekly_task_before_its_first_run_is_waiting(self):
        row = self.rows()['news']
        self.assertEqual(row.state, health.WAIT)
        self.assertIn('10/5', row.result)

    def test_monday_briefing_not_built_by_eight_is_worth_a_look(self):
        put(marketing_last_news_scan='2026-10-05')
        self.assertEqual(self.rows(kst(2026, 10, 5, 7, 59))['brief_build'].state, health.WAIT)
        self.assertEqual(self.rows(kst(2026, 10, 5, 8, 0))['brief_build'].state, health.WARN)

    def test_last_weeks_briefing_that_was_sent_is_ok(self):
        Briefing.objects.create(week_start=date(2026, 9, 28), sent_at=kst(2026, 9, 30, 10, 0))
        self.assertEqual(self.rows()['brief_send'].state, health.OK)

    def test_monthly_review_waits_until_the_fifth_then_needs_a_look(self):
        put(bnk_mode='on', monthly_mode='live', bnk_last_monthly='2026-09')
        self.assertEqual(self.rows()['monthly'].state, health.OK)
        self.assertEqual(self.rows(kst(2026, 11, 2, 12, 0))['monthly'].state, health.WAIT)
        self.assertEqual(self.rows(kst(2026, 11, 5, 12, 0))['monthly'].state, health.WARN)

    # ---- 주기 작업 · 워커 · 텔레그램 ----

    def test_drive_scan_older_than_thirty_minutes_is_worth_a_look(self):
        put(drive_autoscan=True, last_drive_scan=(self.NOW - timedelta(minutes=5)).isoformat())
        self.assertNotEqual(self.rows()['drive'].state, health.WARN)
        put(last_drive_scan=(self.NOW - timedelta(minutes=31)).isoformat())
        self.assertEqual(self.rows()['drive'].state, health.WARN)

    def test_drive_counts_drafts_not_baseline_folders_and_flags_failed_sources(self):
        from intake.models import IntakeSource
        put(drive_autoscan=True, last_drive_scan=(self.NOW - timedelta(minutes=5)).isoformat())
        IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='옛 폴더', status=IntakeSource.BASELINE)
        row = self.rows()['drive']
        self.assertEqual(row.state, health.CALM)
        self.assertIn('신간 초안 0개', row.result)
        IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='새 책', status=IntakeSource.FAILED)
        row = self.rows()['drive']
        self.assertEqual(row.state, health.WARN)
        self.assertIn('/retry', row.reason)

    def test_worker_that_stopped_ticking_is_worth_a_look(self):
        put(marketing_last_kit_check=(self.NOW - timedelta(minutes=3)).isoformat())
        self.assertEqual(self.rows()['worker'].state, health.OK)
        put(marketing_last_kit_check=(self.NOW - timedelta(minutes=40)).isoformat())
        self.assertEqual(self.rows()['worker'].state, health.WARN)

    def test_stopped_worker_is_listed_first_because_it_explains_the_rest(self):
        put(marketing_last_review_scan='2026-10-01',
            marketing_last_kit_check=(self.NOW - timedelta(hours=30)).isoformat())
        self.assertEqual(health.watch(health.evaluate(self.NOW))[0].key, 'worker')

    def test_telegram_outage_is_worth_a_look_only_from_the_third_failure(self):
        since = (self.NOW - timedelta(minutes=2)).isoformat()
        put(telegram_poll_outage={'since': since, 'fails': 1, 'alerted': False, 'error': 'timeout'})
        self.assertNotEqual(self.rows()['telegram'].state, health.WARN)
        put(telegram_poll_outage={'since': since, 'fails': 3, 'alerted': True, 'error': 'timeout'})
        self.assertEqual(self.rows()['telegram'].state, health.WARN)

    def test_last_telegram_outage_is_described(self):
        put(telegram_poll_last_outage={'since': kst(2026, 10, 2, 6, 7).isoformat(),
                                       'until': kst(2026, 10, 2, 6, 8).isoformat(), 'fails': 1, 'error': 'x'})
        self.assertIn('10/2 06:07', self.rows()['telegram'].result)

    # ---- 화면에 나가는 값 ----

    def test_values_of_unlisted_state_keys_never_appear(self):
        put(marketing_notion_db='notion-db-secret-id', some_token='sk-secret-value',
            marketing_error_review='2026-10-03')
        text = repr(health.evaluate(self.NOW))
        self.assertNotIn('notion-db-secret-id', text)
        self.assertNotIn('sk-secret-value', text)

    def test_summary_lists_only_rows_worth_a_look(self):
        put(marketing_last_review_scan='2026-10-03', review_fail_daum_cafe=1)
        rows = health.evaluate(self.NOW)
        lines = health.summary_lines(rows)
        self.assertTrue(any('독자 서평' in line and 'review_fail_daum_cafe' in line for line in lines))
        self.assertEqual(len(lines), 1 + len(health.watch(rows)))
        self.assertFalse(any('서점 버튼 클릭' in line for line in lines))   # 정상·새로 찾은 것 없음 줄은 빠진다

    def test_summary_says_all_fine_when_nothing_needs_a_look(self):
        rows = [r for r in health.evaluate(self.NOW) if r.state != health.WARN]
        self.assertIn('모두 정상', health.summary_lines(rows)[0])
