from datetime import date, datetime, timedelta
from unittest import mock

from django.test import TestCase

from intake.models import WorkerState
from marketing.models import Briefing, Proposal, SalesSnapshot, Signal
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

    # ---- 리뷰 반영: 오류는 판정하는 주기 안의 것만, 지난 일은 결과 칸으로 ----

    def test_yesterdays_error_does_not_haunt_a_daily_task_that_ran_today(self):
        put(marketing_last_review_scan='2026-10-03', marketing_error_review='2026-10-02')
        self.assertNotEqual(self.rows()['review'].state, health.WARN)

    def test_weekly_failure_is_worth_a_look_on_its_day_and_the_next_then_becomes_history(self):
        put(marketing_last_loan_scan='2026-10-03', marketing_error_loan='2026-10-03')
        self.assertEqual(self.rows(kst(2026, 10, 4, 9, 0))['loans'].state, health.WARN)
        later = self.rows(kst(2026, 10, 6, 9, 0))['loans']
        self.assertNotEqual(later.state, health.WARN)
        self.assertIn('지난 일', later.result)
        self.assertIn('marketing_error_loan', later.result)

    def test_missed_briefing_is_not_repeated_all_week(self):
        Briefing.objects.create(week_start=date(2026, 10, 5))
        put(marketing_last_news_scan='2026-10-05', marketing_last_brief_week='2026-10-05',
            marketing_brief_missed='2026-10-05')
        self.assertEqual(self.rows(kst(2026, 10, 5, 21, 30))['brief_send'].state, health.CALM)  # 항목 없는 브리핑
        b = Briefing.objects.get()
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, briefing=b, headline='x')
        self.assertEqual(self.rows(kst(2026, 10, 5, 21, 30))['brief_send'].state, health.WARN)
        self.assertNotEqual(self.rows(kst(2026, 10, 7, 9, 0))['brief_send'].state, health.WARN)

    def test_briefing_being_built_right_now_is_not_a_problem_yet(self):
        put(marketing_last_news_scan='2026-10-05', marketing_last_brief_week='2026-10-05')
        self.assertNotEqual(self.rows(kst(2026, 10, 5, 7, 5))['brief_build'].state, health.WARN)
        self.assertEqual(self.rows(kst(2026, 10, 5, 8, 1))['brief_build'].state, health.WARN)

    def test_missing_the_previous_cycle_too_is_worth_a_look_even_inside_the_grace(self):
        put(marketing_last_review_scan='2026-10-01')
        self.assertEqual(self.rows(kst(2026, 10, 3, 5, 0))['review'].state, health.WARN)

    def test_bnk_login_block_is_shown_as_the_cause(self):
        put(bnk_mode='on', bnk_login_blocked='2026-10-03', bnk_last_run='2026-10-02')
        row = self.rows()['bnk']
        self.assertEqual(row.state, health.WARN)
        self.assertIn('/bnk on', row.reason)
        self.assertNotIn('돌지 않았어요', row.reason)

    def test_monthly_review_is_late_only_after_the_fifths_send_time(self):
        put(bnk_mode='on', monthly_mode='live', bnk_last_monthly='2026-09')
        self.assertEqual(self.rows(kst(2026, 11, 5, 9, 0))['monthly'].state, health.WAIT)
        self.assertEqual(self.rows(kst(2026, 11, 5, 10, 31))['monthly'].state, health.WARN)

    def test_partner_row_sees_the_sunday_instagram_error_and_token_line_appears_once(self):
        put(marketing_last_instagram_scan='2026-10-04', marketing_error_instagram='2026-10-04')
        with self.settings(MARKETING={'META_ACCESS_EXPIRES': '2026-10-08'}), \
                mock.patch('marketing.meta.ig_configured', return_value=True):
            rows = self.rows(kst(2026, 10, 4, 9, 0))
        self.assertEqual(rows['partner'].state, health.WARN)
        self.assertNotIn('토큰', rows['partner'].reason)
        self.assertIn('토큰', rows['instagram'].reason)

    def test_old_failed_sources_and_kits_of_books_out_of_the_window_do_not_warn_forever(self):
        from intake.models import IntakeSource
        put(drive_autoscan=True, last_drive_scan=(self.NOW - timedelta(minutes=5)).isoformat(),
            marketing_last_kit_check=(self.NOW - timedelta(minutes=5)).isoformat(),
            marketing_kit_failures={'999': {'day': '2026-07-01', 'count': 3}})
        src = IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='옛 실패', status=IntakeSource.FAILED)
        IntakeSource.objects.filter(pk=src.pk).update(updated_at=self.NOW - timedelta(days=8))
        rows = self.rows()
        self.assertNotEqual(rows['drive'].state, health.WARN)
        self.assertNotEqual(rows['kit'].state, health.WARN)

    def test_notice_that_already_ended_is_not_counted(self):
        from web.models import Notice
        Notice.objects.create(message='끝난 알림', state=Notice.POSTED, starts_at=self.NOW - timedelta(days=9),
                              ends_at=self.NOW - timedelta(days=1))
        self.assertIn('게시 중 0건', self.rows()['notice'].result)

    def test_worker_blames_telegram_when_polling_is_down(self):
        since = (self.NOW - timedelta(minutes=45)).isoformat()
        put(marketing_last_kit_check=(self.NOW - timedelta(minutes=45)).isoformat(),
            telegram_poll_outage={'since': since, 'fails': 30, 'alerted': True, 'error': 'x'})
        rows = health.evaluate(self.NOW)
        worker = {r.key: r for r in rows}['worker']
        self.assertIn('텔레그램', worker.reason)
        self.assertNotIn('systemctl', worker.reason)
        self.assertEqual(health.watch(rows)[0].key, 'telegram')

    def test_one_broken_row_does_not_break_the_page(self):
        put(marketing_last_sales_scan='2026-10-03', marketing_sales_fail_streak='망가진 값')
        rows = self.rows()
        self.assertEqual(rows['sales'].state, health.WARN)
        self.assertIn('판정 오류', rows['sales'].reason)
        self.assertIn('review', rows)

    def test_late_rows_own_error_is_not_repeated_as_another_error(self):
        put(marketing_last_review_scan='2026-10-02', marketing_error_review='2026-10-03')
        rows = self.rows()
        self.assertIn('marketing_error_review', rows['review'].reason)
        self.assertNotIn('errors', rows)

    def test_social_without_its_settings_names_the_cause(self):
        put(marketing_social='on')
        with self.settings(MARKETING={}):
            row = self.rows()['social']
        self.assertEqual(row.state, health.WARN)
        self.assertIn('APIFY_TOKEN', row.reason)

    # ---- 재검토 반영 ----

    def test_monthly_review_sent_after_a_failed_try_is_fine(self):
        put(bnk_mode='on', monthly_mode='live', bnk_last_monthly='2026-10', marketing_error_monthly='2026-11-03')
        self.assertEqual(self.rows(kst(2026, 11, 12, 9, 0))['monthly'].state, health.OK)

    def test_briefing_sent_after_a_failed_try_is_fine(self):
        Briefing.objects.create(week_start=date(2026, 10, 5), sent_at=kst(2026, 10, 5, 9, 45))
        put(marketing_error_brief_send='2026-10-05')
        self.assertEqual(self.rows(kst(2026, 10, 6, 9, 0))['brief_send'].state, health.OK)

    def test_a_broken_weekly_row_is_not_hidden_as_history(self):
        put(marketing_last_news_scan='2026-10-05')
        with mock.patch('ops.health._news', side_effect=RuntimeError('bug')):
            row = self.rows(kst(2026, 10, 8, 9, 0))['news']
        self.assertEqual(row.state, health.WARN)
        self.assertIn('판정 오류', row.reason)

    def test_errors_of_switched_off_rows_still_show_up(self):
        put(midweek_mode='off', marketing_error_midweek='2026-10-03')
        warn = health.watch(health.evaluate(self.NOW))
        self.assertTrue(any('marketing_error_midweek' in r.reason for r in warn))

    def test_manual_run_before_the_schedule_is_not_a_missed_run(self):
        put(grant_mode='live', grant_last_scan='2026-10-03')
        self.assertNotEqual(self.rows(kst(2026, 10, 3, 6, 0))['grant'].state, health.WARN)

    def test_old_failed_sources_stay_visible_without_warning(self):
        from intake.models import IntakeSource
        put(drive_autoscan=True, last_drive_scan=(self.NOW - timedelta(minutes=5)).isoformat())
        src = IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='옛 실패', status=IntakeSource.FAILED)
        IntakeSource.objects.filter(pk=src.pk).update(updated_at=self.NOW - timedelta(days=8))
        row = self.rows()['drive']
        self.assertNotEqual(row.state, health.WARN)
        self.assertIn('실패', row.result)

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

    ADS = {'META_ADS_TOKEN': 'a', 'META_AD_ACCOUNT_ID': 'act_1', 'META_APP_SECRET': 's', 'META_PAGE_TOKEN': 'p',
           'META_PAGE_ID': '111', 'META_IG_USER_ID': '222', 'META_ADS_EXPIRES': '2026-11-30'}

    def test_ads_row_is_off_without_the_token(self):
        self.assertEqual(self.rows()['ads'].state, health.OFF)

    def test_ads_row_ok_after_a_successful_run_and_shows_the_expiry(self):
        put(marketing_last_ads_scan='2026-10-03', ads_ok_on='2026-10-03')
        with self.settings(MARKETING=self.ADS):
            row = self.rows()['ads']
        self.assertEqual(row.state, health.OK)
        self.assertIn('토큰 만료 11/30', row.result)

    def test_ads_row_warns_on_auth_error_and_near_expiry(self):
        put(marketing_last_ads_scan='2026-10-03', ads_auth_alert_day='2026-10-03')
        with self.settings(MARKETING={**self.ADS, 'META_ADS_EXPIRES': '2026-10-09'}):
            row = self.rows()['ads']
        self.assertEqual(row.state, health.WARN)
        self.assertIn('광고 토큰·권한 오류', row.reason)
        self.assertIn('광고 토큰 만료 10/9 — 갱신', row.reason)

    def test_ads_row_counts_today_and_the_six_days_before_as_seven_days(self):
        from marketing.tests.fakes import make_ad
        make_ad(ad_id='1', post_id='111_1', days=[date(2026, 9, 26)], daily=5000)   # 7일 전 — 빠진다
        make_ad(ad_id='2', post_id='111_2', days=[date(2026, 9, 27)], daily=3000)   # 6일 전 — 든다
        put(marketing_last_ads_scan='2026-10-03', ads_ok_on='2026-10-03')
        with self.settings(MARKETING=self.ADS):
            self.assertIn('지난 7일 광고 1개 3,000원', self.rows()['ads'].result)

    def test_ads_row_warns_on_a_late_card_only_when_cards_are_on(self):
        from marketing.tests.fakes import make_ad
        make_ad(days=[date(2026, 9, 21), date(2026, 9, 22)])   # 10/3 기준 11일 지남
        put(marketing_last_ads_scan='2026-10-03', ads_ok_on='2026-10-03')
        with self.settings(MARKETING=self.ADS):
            self.assertNotEqual(self.rows()['ads'].state, health.WARN)
            put(ads_card_mode='admin_only')
            self.assertIn('결과 카드를 못 보낸 광고 1개', self.rows()['ads'].reason)
