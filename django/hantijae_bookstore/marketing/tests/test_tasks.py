from datetime import date, datetime, timedelta, timezone as dt_tz
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from intake.models import WorkerState
from marketing import tasks
from marketing.models import Briefing, Proposal
from marketing.timeutil import KST


class FakeMarketing:
    def __init__(self, mode):
        self._mode, self.kits_sent, self.briefs_sent, self.blog_reads = mode, 0, [], 0

    def mode(self):
        return self._mode

    def blog_posts(self):
        self.blog_reads += 1
        return []

    def send_pending_kits(self, now):
        self.kits_sent += 1
        return 0

    def send_briefing(self, b, now):
        self.briefs_sent.append(b.id)
        return True

    def send_midweek(self, now):
        self.midweek_sends = getattr(self, 'midweek_sends', 0) + 1
        return False

    def send_grants(self, now):
        self.grant_sends = getattr(self, 'grant_sends', 0) + 1
        return 0


class FakeBot:
    def __init__(self, mode):
        from marketing.tests.fakes import FakeTG
        self.marketing, self.notes, self.tg = FakeMarketing(mode), [], FakeTG()

    def notify_admin(self, text, html=False):
        self.notes.append(text)

    def review_chat_id(self):
        return -200

    def _chat(self, kind):
        return 100


class Deps:
    def __init__(self, mode='live'):
        self.bot, self.llm = FakeBot(mode), object()


@mock.patch('marketing.tasks.kit.build_pending', return_value=[])
@mock.patch('marketing.tasks.briefing.build_weekly',
            return_value=(mock.Mock(**{'items.exists.return_value': True}), []))
@mock.patch('marketing.tasks.news.collect_news', return_value=[])
@mock.patch('marketing.tasks.funding.collect_funding', return_value=0)
@mock.patch('marketing.tasks.sales.collect_sales', return_value=(0, []))
class RunDueTest(TestCase):
    def setUp(self):
        patcher = mock.patch('marketing.tasks.selections.run_scan', return_value=[])
        self.selection_scan = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('marketing.tasks.social.run_due')
        self.social_step = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('marketing.tasks.reviews.run')
        self.review_scan = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('marketing.tasks.mentions.run')
        self.web_scan = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('marketing.tasks.instagram.run')
        self.instagram_scan = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('marketing.tasks.loans.run')
        self.loan_scan = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('marketing.tasks.ads.run')
        self.ads_scan = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('marketing.tasks.ads.send_due_cards', return_value=0)
        self.ads_cards = patcher.start()
        self.addCleanup(patcher.stop)

    def test_ad_cards_are_checked_every_loop_unless_marketing_off(self, *_):
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 29, 10, 0, tzinfo=KST))
        self.assertIs(self.ads_cards.call_args.args[0], deps.bot)
        tasks.run_due(Deps('off'), datetime(2026, 9, 29, 10, 1, tzinfo=KST))
        self.assertEqual(self.ads_cards.call_count, 1)

    def test_ads_scan_once_per_day_after_0650_and_notes_wait_for_the_morning(self, *_):
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 29, 6, 49, tzinfo=KST))
        self.ads_scan.assert_not_called()
        tasks.run_due(deps, datetime(2026, 9, 29, 6, 50, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 29, 9, 0, tzinfo=KST))
        self.assertEqual(self.ads_scan.call_count, 1)
        self.assertEqual(self.ads_scan.call_args.args, (date(2026, 9, 29),))
        self.ads_scan.call_args.kwargs['notify']('토큰 안내')
        self.assertEqual(deps.bot.notes, [])   # 06:50 = 조용한 시간 → 08시 뒤에
        self.assertIn('토큰 안내', WorkerState.get(tasks.ADMIN_QUEUE))

    def test_off_mode_skips_ads_scan(self, *_):
        tasks.run_due(Deps('off'), datetime(2026, 9, 29, 7, 0, tzinfo=KST))
        self.ads_scan.assert_not_called()

    def test_social_step_runs_every_loop_unless_off(self, *_):
        tasks.run_due(Deps(), datetime(2026, 9, 29, 3, 0, tzinfo=KST))
        tasks.run_due(Deps(), datetime(2026, 9, 29, 3, 1, tzinfo=KST))
        self.assertEqual(self.social_step.call_count, 2)
        tasks.run_due(Deps('off'), datetime(2026, 9, 29, 7, 0, tzinfo=KST))
        self.assertEqual(self.social_step.call_count, 2)

    def test_run_due_retries_pending_notion_pages(self, *_):
        deps = Deps()
        with mock.patch('marketing.tasks.notion_sync.retry_pending', return_value=0) as retry:
            tasks.run_due(deps, datetime(2026, 9, 29, 10, 0, tzinfo=KST))
        retry.assert_called_once()
        self.assertIs(retry.call_args.args[0], deps.bot)
        self.assertEqual(deps.bot.notes, [])  # 가짜 deps에 tg가 없어도 오류 알림이 나가지 않는다

    def test_run_due_flushes_notion_pages_every_loop(self, *_):
        deps = Deps()
        with mock.patch('marketing.tasks.notion_sync.flush', return_value=0) as flush:
            tasks.run_due(deps, datetime(2026, 9, 29, 23, 0, tzinfo=KST))  # 방에 보내지 않으니 밤에도
            tasks.run_due(deps, datetime(2026, 9, 29, 23, 1, tzinfo=KST))
        self.assertEqual(flush.call_count, 2)
        self.assertIs(flush.call_args.args[0], deps.bot)

    def test_off_mode_does_nothing(self, sales_, fund_, news_, brief_, kit_):
        tasks.run_due(Deps('off'), datetime(2026, 9, 28, 7, 0, tzinfo=KST))
        for m in (sales_, fund_, news_, brief_, kit_):
            m.assert_not_called()

    def test_sales_once_per_kst_day_after_six(self, sales_, *_):
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 28, 5, 59, tzinfo=KST))
        sales_.assert_not_called()
        tasks.run_due(deps, datetime(2026, 9, 28, 6, 0, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 28, 18, 0, tzinfo=KST))
        self.assertEqual(sales_.call_count, 1)

    def test_brief_built_on_kst_monday(self, sales_, fund_, news_, brief_, kit_):
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 27, 21, 0, tzinfo=dt_tz.utc))  # 월 06:00 KST
        brief_.assert_not_called()
        tasks.run_due(deps, datetime(2026, 9, 27, 22, 0, tzinfo=dt_tz.utc))  # 월 07:00 KST
        tasks.run_due(deps, datetime(2026, 9, 27, 23, 0, tzinfo=dt_tz.utc))
        self.assertEqual(brief_.call_count, 1)
        news_.assert_called_once()

    def test_no_brief_on_other_days(self, sales_, fund_, news_, brief_, kit_):
        tasks.run_due(Deps(), datetime(2026, 9, 29, 7, 0, tzinfo=KST))
        brief_.assert_not_called()
        news_.assert_not_called()

    def test_brief_sent_from_0930_on_monday(self, *_):
        deps = Deps()
        b = Briefing.objects.create(week_start=date(2026, 9, 28))
        WorkerState.put('marketing_last_brief_week', '2026-09-28')
        tasks.run_due(deps, datetime(2026, 9, 28, 9, 29, tzinfo=KST))
        self.assertEqual(deps.bot.marketing.briefs_sent, [])
        tasks.run_due(deps, datetime(2026, 9, 28, 9, 30, tzinfo=KST))
        self.assertEqual(deps.bot.marketing.briefs_sent, [b.id])

    def test_missed_brief_notifies_admin_once(self, *_):
        deps = Deps()
        b = Briefing.objects.create(week_start=date(2026, 9, 28))
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, briefing=b, headline='h')
        WorkerState.put('marketing_last_brief_week', '2026-09-28')
        tasks.run_due(deps, datetime(2026, 9, 28, 21, 5, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 28, 22, 5, tzinfo=KST))
        self.assertEqual(len([n for n in deps.bot.notes if '브리핑' in n]), 1)
        self.assertEqual(deps.bot.marketing.briefs_sent, [])

    def test_empty_briefing_gets_no_missed_notice_at_give_up_time(self, *_):
        """07:00에 이미 '후보 없음'을 알렸다면 21:00에 또 알리지 않는다."""
        deps = Deps()
        Briefing.objects.create(week_start=date(2026, 9, 28))  # 항목 0개
        WorkerState.put('marketing_last_brief_week', '2026-09-28')
        tasks.run_due(deps, datetime(2026, 9, 28, 21, 5, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 28, 22, 5, tzinfo=KST))
        self.assertEqual([n for n in deps.bot.notes if '브리핑' in n], [])
        self.assertEqual(deps.bot.marketing.briefs_sent, [])

    def test_empty_scheduled_briefing_notifies_admin_with_reasons(self, sales_, fund_, news_, brief_, kit_):
        deps = Deps()
        brief_.return_value = (Briefing.objects.create(week_start=date(2026, 9, 28)), ['blog:1: 빈 항목', '없는 후보: x'])
        tasks.run_due(deps, datetime(2026, 9, 28, 7, 0, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 28, 8, 0, tzinfo=KST))
        self.assertEqual([n for n in deps.bot.notes if '후보가 없거나' in n],
                         ['⏭️ 이번 주 브리핑 후보가 없거나 모두 걸렀어요\n버린 항목: blog:1: 빈 항목; 없는 후보: x'])

    def test_lost_briefing_build_notifies_once_at_give_up_time(self, *_):
        deps = Deps()
        WorkerState.put('marketing_last_brief_week', '2026-09-28')  # 만들다가 워커가 멈춰 Briefing이 없다
        tasks.run_due(deps, datetime(2026, 9, 28, 20, 59, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 28, 21, 5, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 28, 22, 5, tzinfo=KST))
        self.assertEqual(len([n for n in deps.bot.notes if '보내지 못했어요' in n]), 1)

    def test_sensitive_news_listed_in_one_admin_message(self, sales_, fund_, news_, brief_, kit_):
        book = SimpleNamespace(title='무지개를 변호하다')
        news_.return_value = [SimpleNamespace(sensitive=True, book=book, title='부고 기사'),
                              SimpleNamespace(sensitive=False, book=book, title='칼럼'),
                              SimpleNamespace(sensitive=True, book=book, title='재판 기사')]
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 28, 6, 30, tzinfo=KST))
        notes = [n for n in deps.bot.notes if '민감' in n]
        self.assertEqual(len(notes), 1)
        self.assertIn('부고 기사', notes[0])
        self.assertIn('재판 기사', notes[0])
        self.assertNotIn('칼럼', notes[0])

    @mock.patch('marketing.tasks.kit.buildable_books', return_value=['책'])
    def test_kit_check_every_ten_minutes_and_error_notified_once(self, buildable_, sales_, fund_, news_, brief_, kit_):
        deps = Deps()
        kit_.side_effect = RuntimeError('sidecar down')
        t = datetime(2026, 9, 29, 12, 0, tzinfo=KST)
        for minute in (0, 5, 10):
            tasks.run_due(deps, t.replace(minute=minute))
        self.assertEqual(kit_.call_count, 2)
        self.assertEqual(len([n for n in deps.bot.notes if '마케팅 kit 실패' in n]), 1)
        self.assertEqual(deps.bot.marketing.kits_sent, 3)

    def test_kit_send_failure_notifies_admin_once_per_day(self, sales_, fund_, news_, brief_, kit_):
        deps = Deps()
        deps.bot.marketing.send_pending_kits = mock.Mock(side_effect=RuntimeError('telegram down'))
        t = datetime(2026, 9, 29, 12, 0, tzinfo=KST)
        with self.assertLogs('intake', level='ERROR'):
            tasks.run_due(deps, t)
            tasks.run_due(deps, t.replace(hour=13))
            self.assertEqual(len([n for n in deps.bot.notes if '마케팅 kit_send 실패' in n]), 1)
            tasks.run_due(deps, t + timedelta(days=1))
            self.assertEqual(len([n for n in deps.bot.notes if '마케팅 kit_send 실패' in n]), 2)

    def test_kit_build_reads_blog_only_when_a_book_is_buildable(self, sales_, fund_, news_, brief_, kit_):
        deps = Deps()
        t = datetime(2026, 9, 29, 12, 0, tzinfo=KST)
        tasks.run_due(deps, t)
        self.assertEqual(deps.bot.marketing.blog_reads, 0)
        kit_.assert_not_called()
        with mock.patch('marketing.tasks.kit.buildable_books', return_value=['책']):
            tasks.run_due(deps, t.replace(minute=10))
        self.assertEqual(deps.bot.marketing.blog_reads, 1)
        self.assertEqual(kit_.call_args.kwargs['notify'], deps.bot.notify_admin)

    def test_run_due_never_raises_and_reports_once(self, sales_, fund_, news_, brief_, kit_):
        deps = Deps()
        deps.bot.marketing.mode = mock.Mock(side_effect=RuntimeError('db down'))
        tasks.run_due(deps, datetime(2026, 9, 28, 7, 0, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 28, 18, 0, tzinfo=KST))
        self.assertEqual(len([n for n in deps.bot.notes if '마케팅 run_due 실패' in n]), 1)

    def test_sales_failure_streak_notifies_on_third_day(self, sales_, fund_, news_, brief_, kit_):
        deps = Deps()
        sales_.return_value = (0, ['책'])
        tasks.run_due(deps, datetime(2026, 9, 28, 6, 0, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 29, 6, 0, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 30, 6, 0, tzinfo=KST))
        self.assertEqual(len([n for n in deps.bot.notes if '3일째' in n]), 1)
        tasks.run_due(deps, datetime(2026, 10, 1, 6, 0, tzinfo=KST))
        self.assertEqual(len([n for n in deps.bot.notes if '3일째' in n]), 1)

        sales_.return_value = (5, [])
        tasks.run_due(deps, datetime(2026, 10, 2, 6, 0, tzinfo=KST))
        self.assertEqual(WorkerState.get('marketing_sales_fail_streak'), 0)

    def test_selection_scan_once_per_day_after_0610(self, *_):
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 29, 6, 9, tzinfo=KST))
        self.selection_scan.assert_not_called()
        tasks.run_due(deps, datetime(2026, 9, 29, 6, 10, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 29, 12, 0, tzinfo=KST))
        self.assertEqual(self.selection_scan.call_count, 1)

    def test_placement_scan_once_per_day_after_noon(self, *_):
        deps = Deps()
        with mock.patch('marketing.tasks.placements.update_recent', return_value=0) as scan:
            tasks.run_due(deps, datetime(2026, 9, 30, 11, 59, tzinfo=KST))
            scan.assert_not_called()
            tasks.run_due(deps, datetime(2026, 9, 30, 12, 0, tzinfo=KST))
            tasks.run_due(deps, datetime(2026, 9, 30, 15, 0, tzinfo=KST))
        self.assertEqual(scan.call_count, 1)
        self.assertEqual(deps.bot.marketing.blog_reads, 0)  # 블로그는 찾을 글이 있을 때만(placements가 부름) 읽는다
        scan.call_args.kwargs['blog_posts']()
        self.assertEqual(deps.bot.marketing.blog_reads, 1)

    def test_off_mode_skips_selection_scan(self, *_):
        tasks.run_due(Deps('off'), datetime(2026, 9, 29, 7, 0, tzinfo=KST))
        self.selection_scan.assert_not_called()

    def test_review_scan_once_per_day_after_0430(self, *_):
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 29, 4, 29, tzinfo=KST))
        self.review_scan.assert_not_called()
        tasks.run_due(deps, datetime(2026, 9, 29, 4, 30, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 29, 12, 0, tzinfo=KST))
        self.assertEqual(self.review_scan.call_count, 1)
        self.assertEqual(self.review_scan.call_args.args, (deps, date(2026, 9, 29)))

    def test_off_mode_skips_review_scan(self, *_):
        tasks.run_due(Deps('off'), datetime(2026, 9, 29, 5, 0, tzinfo=KST))
        self.review_scan.assert_not_called()

    def test_review_scan_notify_waits_for_the_morning(self, *_):
        """04:30은 조용한 시간(21~08시) 안 — 서평 수집이 직접 부르는 notify는 바로 보내지 않고 아침까지 모아 둔다."""
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 29, 4, 30, tzinfo=KST))
        notify = self.review_scan.call_args.kwargs['notify']
        notify('x')
        self.assertEqual(WorkerState.get('moment_admin_queue'), ['x'])
        self.assertEqual(deps.bot.notes, [])

    def test_web_scan_once_per_day_after_0440(self, *_):
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 29, 4, 39, tzinfo=KST))
        self.web_scan.assert_not_called()
        tasks.run_due(deps, datetime(2026, 9, 29, 4, 40, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 29, 12, 0, tzinfo=KST))
        self.assertEqual(self.web_scan.call_count, 1)
        self.assertEqual(self.web_scan.call_args.args[:2], (deps, date(2026, 9, 29)))
        self.web_scan.call_args.kwargs['notify']('x')   # 04:40 알림은 아침까지 모아 둔다
        self.assertEqual(WorkerState.get('moment_admin_queue'), ['x'])
        self.assertEqual(deps.bot.notes, [])

    def test_instagram_scan_once_per_day_after_0450(self, *_):
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 29, 4, 49, tzinfo=KST))
        self.instagram_scan.assert_not_called()
        tasks.run_due(deps, datetime(2026, 9, 29, 4, 50, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 29, 12, 0, tzinfo=KST))
        self.assertEqual(self.instagram_scan.call_count, 1)
        self.assertEqual(self.instagram_scan.call_args.args[:2], (deps, date(2026, 9, 29)))
        notify = self.instagram_scan.call_args.kwargs['notify']
        notify('x')   # 04:50에 부른 알림은 아침까지 모아 둔다
        self.assertEqual(deps.bot.notes, [])

    def test_off_mode_skips_instagram_scan(self, *_):
        tasks.run_due(Deps('off'), datetime(2026, 9, 29, 5, 0, tzinfo=KST))
        self.instagram_scan.assert_not_called()

    def test_loan_scan_on_saturday_after_0540(self, *_):
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 10, 2, 6, 0, tzinfo=KST))   # 금요일
        self.loan_scan.assert_not_called()
        tasks.run_due(deps, datetime(2026, 10, 3, 5, 39, tzinfo=KST))
        self.loan_scan.assert_not_called()
        tasks.run_due(deps, datetime(2026, 10, 3, 5, 40, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 10, 3, 12, 0, tzinfo=KST))
        self.assertEqual(self.loan_scan.call_count, 1)
        self.assertEqual(self.loan_scan.call_args.args[0], date(2026, 10, 3))
        self.loan_scan.call_args.kwargs['notify']('x')   # 05:40에 부른 알림은 아침까지 모아 둔다
        self.assertEqual(deps.bot.notes, [])

    def test_review_failure_is_reported_once_and_loop_goes_on(self, sales_, *_):
        self.review_scan.side_effect = RuntimeError('판별 실패')
        deps = Deps()
        with self.assertLogs('intake', level='ERROR'):
            tasks.run_due(deps, datetime(2026, 9, 29, 6, 0, tzinfo=KST))
            tasks.run_due(deps, datetime(2026, 9, 30, 6, 0, tzinfo=KST))
        self.assertEqual(len([n for n in deps.bot.notes if '마케팅 review 실패' in n]), 2)   # 날마다 한 번
        self.assertEqual(sales_.call_count, 2)


@mock.patch('marketing.tasks.kit.build_pending', return_value=[])
@mock.patch('marketing.tasks.briefing.build_weekly',
            return_value=(mock.Mock(**{'items.exists.return_value': True}), []))
@mock.patch('marketing.tasks.news.collect_news', return_value=[])
@mock.patch('marketing.tasks.funding.collect_funding', return_value=0)
@mock.patch('marketing.tasks.sales.collect_sales', return_value=(0, []))
class MomentScheduleTest(TestCase):
    TUE = datetime(2026, 9, 29, 5, 0, tzinfo=KST)

    def setUp(self):
        # 바깥 수집은 이 클래스가 보는 것이 아니다 — 시험 중에 실제 사이트에 요청하지 않게 막는다
        for target in ('marketing.tasks.loans.run', 'marketing.tasks.mentions.run',
                       'marketing.tasks.selections.run_scan', 'marketing.tasks.social.run_due',
                       'marketing.tasks.reviews.run', 'marketing.tasks.instagram.run'):
            patcher = mock.patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_moment_runs_once_after_five_only_when_on(self, *_):
        from marketing.moments import Report
        deps = Deps()
        with mock.patch('marketing.tasks.moments.daily', return_value=Report(dropped=['x: 근거 없음'])) as daily:
            tasks.run_due(deps, self.TUE)
            daily.assert_not_called()
            WorkerState.put('moment_mode', 'admin_only')
            tasks.run_due(deps, self.TUE - timedelta(minutes=1))
            daily.assert_not_called()
            tasks.run_due(deps, self.TUE)
            tasks.run_due(deps, self.TUE + timedelta(hours=3))
            self.assertEqual(daily.call_count, 1)
        self.assertTrue(any('대화 속 계기' in n and '근거 없음' in n for n in deps.bot.notes))

    def test_moment_failure_is_reported_and_loop_goes_on(self, sales_, *_):
        WorkerState.put('moment_mode', 'live')
        deps = Deps()
        with mock.patch('marketing.tasks.moments.daily', side_effect=RuntimeError('db')):
            tasks.run_due(deps, self.TUE + timedelta(hours=1))
        self.assertTrue(any('마케팅 moment 실패' in n for n in deps.bot.notes))
        sales_.assert_called_once()

    def test_moment_runs_before_monday_brief(self, sales_, fund_, news_, brief_, kit_):
        WorkerState.put('moment_mode', 'live')
        order = []
        brief_.side_effect = lambda *a, **k: order.append('brief') or (mock.Mock(**{'items.exists.return_value': True}), [])
        from marketing.moments import Report
        with mock.patch('marketing.tasks.moments.daily', side_effect=lambda *a, **k: order.append('moment') or Report()):
            tasks.run_due(Deps(), datetime(2026, 9, 28, 7, 5, tzinfo=KST))
        self.assertEqual(order, ['moment', 'brief'])

    def test_midweek_build_and_send_times(self, *_):
        WorkerState.put('midweek_mode', 'admin_only')
        deps = Deps()
        with mock.patch('marketing.tasks.midweek.build', return_value=([], [])) as build:
            tasks.run_due(deps, datetime(2026, 9, 28, 9, 30, tzinfo=KST))  # 월요일: 안 함
            tasks.run_due(deps, datetime(2026, 9, 29, 5, 29, tzinfo=KST))
            build.assert_not_called()
            tasks.run_due(deps, datetime(2026, 9, 29, 5, 30, tzinfo=KST))
            tasks.run_due(deps, datetime(2026, 9, 29, 9, 29, tzinfo=KST))
            self.assertEqual((build.call_count, getattr(deps.bot.marketing, 'midweek_sends', 0)), (1, 0))
            tasks.run_due(deps, datetime(2026, 9, 29, 9, 30, tzinfo=KST))
            tasks.run_due(deps, datetime(2026, 9, 29, 21, 0, tzinfo=KST))
        self.assertEqual(deps.bot.marketing.midweek_sends, 1)

    def test_midweek_off_does_nothing(self, *_):
        deps = Deps()
        with mock.patch('marketing.tasks.midweek.build') as build:
            tasks.run_due(deps, datetime(2026, 9, 29, 9, 40, tzinfo=KST))
        build.assert_not_called()
        self.assertEqual(getattr(deps.bot.marketing, 'midweek_sends', 0), 0)

    def test_late_start_builds_then_sends(self, *_):
        WorkerState.put('midweek_mode', 'live')
        deps, order = Deps(), []
        deps.bot.marketing.send_midweek = lambda now: order.append('send') or True
        with mock.patch('marketing.tasks.midweek.build', side_effect=lambda *a: order.append('build') or ([], ['x: 없는 후보'])):
            tasks.run_due(deps, datetime(2026, 9, 29, 9, 40, tzinfo=KST))
        self.assertEqual(order, ['build', 'send'])
        self.assertTrue(any('주중 제안에서 버린 항목' in n for n in deps.bot.notes))


@mock.patch('marketing.tasks.kit.build_pending', return_value=[])
@mock.patch('marketing.tasks.briefing.build_weekly',
            return_value=(mock.Mock(**{'items.exists.return_value': True}), []))
@mock.patch('marketing.tasks.news.collect_news', return_value=[])
@mock.patch('marketing.tasks.funding.collect_funding', return_value=0)
@mock.patch('marketing.tasks.sales.collect_sales', return_value=(0, []))
class MomentQuietTest(TestCase):
    def setUp(self):
        # 바깥 수집은 이 클래스가 보는 것이 아니다 — 시험 중에 실제 사이트에 요청하지 않게 막는다
        for target in ('marketing.tasks.loans.run', 'marketing.tasks.mentions.run',
                       'marketing.tasks.selections.run_scan', 'marketing.tasks.social.run_due',
                       'marketing.tasks.reviews.run', 'marketing.tasks.instagram.run'):
            patcher = mock.patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_dawn_digest_waits_until_eight(self, *_):
        from marketing.moments import Report
        WorkerState.put('moment_mode', 'admin_only')
        deps = Deps()
        with mock.patch('marketing.tasks.moments.daily', return_value=Report(dropped=['x: 근거 없음'])):
            tasks.run_due(deps, datetime(2026, 9, 29, 5, 0, tzinfo=KST))
            tasks.run_due(deps, datetime(2026, 9, 29, 7, 59, tzinfo=KST))
            self.assertFalse(any('대화 속 계기' in n for n in deps.bot.notes))
            tasks.run_due(deps, datetime(2026, 9, 29, 8, 0, tzinfo=KST))
            tasks.run_due(deps, datetime(2026, 9, 29, 8, 1, tzinfo=KST))
        self.assertEqual(len([n for n in deps.bot.notes if '대화 속 계기' in n]), 1)

    def test_long_build_near_nine_pm_does_not_send_late(self, *_):
        WorkerState.put('midweek_mode', 'live')
        deps = Deps()
        clock = iter([0] + [600] * 10)  # 바퀴 시작 0초, 만들기 뒤 600초(10분) 지남
        with mock.patch('marketing.tasks.time.monotonic', side_effect=lambda: next(clock)), \
                mock.patch('marketing.tasks.midweek.build', return_value=([], [])):
            tasks.run_due(deps, datetime(2026, 9, 29, 20, 55, tzinfo=KST))
        self.assertEqual(getattr(deps.bot.marketing, 'midweek_sends', 0), 0)

    def test_stale_midweek_released_even_when_off(self, *_):
        with mock.patch('marketing.tasks.midweek.release_stale') as release:
            tasks.run_due(Deps(), datetime(2026, 9, 28, 12, 0, tzinfo=KST))
        release.assert_called_once()


@mock.patch('marketing.tasks.kit.build_pending', return_value=[])
@mock.patch('marketing.tasks.briefing.build_weekly',
            return_value=(mock.Mock(**{'items.exists.return_value': True}), []))
@mock.patch('marketing.tasks.news.collect_news', return_value=[])
@mock.patch('marketing.tasks.funding.collect_funding', return_value=0)
@mock.patch('marketing.tasks.sales.collect_sales', return_value=(0, []))
class GrantScheduleTest(TestCase):
    def setUp(self):
        for target in ('marketing.tasks.selections.run_scan', 'marketing.tasks.social.run_due'):
            patcher = mock.patch(target, return_value=[])
            patcher.start()
            self.addCleanup(patcher.stop)
        from marketing import grants
        patcher = mock.patch('marketing.tasks.grants.scan', return_value=grants.ScanReport())
        self.scan = patcher.start()
        self.addCleanup(patcher.stop)

    def test_scan_once_per_day_after_0640_when_on(self, *_):
        WorkerState.put('grant_mode', 'admin_only')
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 30, 6, 39, tzinfo=KST))
        self.scan.assert_not_called()
        tasks.run_due(deps, datetime(2026, 9, 30, 6, 40, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 30, 12, 0, tzinfo=KST))
        self.assertEqual(self.scan.call_count, 1)
        self.assertEqual(WorkerState.get('grant_last_scan'), '2026-09-30')

    def test_grant_mode_off_skips_scan(self, *_):
        tasks.run_due(Deps(), datetime(2026, 9, 30, 7, 0, tzinfo=KST))
        self.scan.assert_not_called()

    def test_digest_waits_for_morning(self, *_):
        from marketing import grants
        WorkerState.put('grant_mode', 'live')
        self.scan.return_value = grants.ScanReport(unannounced=['· 웹소설 공고 — 제목으로 뺌'])
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 30, 6, 40, tzinfo=KST))
        self.assertEqual(deps.bot.notes, [])
        self.assertIn('📋 알리지 않은 지원사업 공고\n· 웹소설 공고 — 제목으로 뺌', WorkerState.get(tasks.ADMIN_QUEUE))

    def test_send_grants_every_loop_unless_marketing_off(self, *_):
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 30, 10, 0, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 30, 10, 1, tzinfo=KST))
        self.assertEqual(deps.bot.marketing.grant_sends, 2)
        off = Deps('off')
        tasks.run_due(off, datetime(2026, 9, 30, 10, 2, tzinfo=KST))
        self.assertFalse(hasattr(off.bot.marketing, 'grant_sends'))


@mock.patch('marketing.tasks.kit.build_pending', return_value=[])
@mock.patch('marketing.tasks.briefing.build_weekly',
            return_value=(mock.Mock(**{'items.exists.return_value': True}), []))
@mock.patch('marketing.tasks.news.collect_news', return_value=[])
@mock.patch('marketing.tasks.funding.collect_funding', return_value=0)
@mock.patch('marketing.tasks.sales.collect_sales', return_value=(0, []))
class BnkScheduleTest(TestCase):
    def setUp(self):
        for target in ('marketing.tasks.selections.run_scan', 'marketing.tasks.social.run_due',
                       'marketing.tasks.reviews.run'):
            patcher = mock.patch(target, return_value=[])
            patcher.start()
            self.addCleanup(patcher.stop)
        from marketing.tests.fakes import FakeBnkClient
        self.client = FakeBnkClient()
        patcher = mock.patch('marketing.tasks.bnk.client_from_settings', return_value=self.client)
        self.factory = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('marketing.tasks.bnk_sales.collect')
        self.collect = patcher.start()
        self.addCleanup(patcher.stop)
        WorkerState.put('bnk_mode', 'on')

    def test_collect_once_per_day_after_0620(self, *_):
        deps = Deps()
        tasks.run_due(deps, datetime(2026, 9, 30, 6, 19, tzinfo=KST))
        self.collect.assert_not_called()
        tasks.run_due(deps, datetime(2026, 9, 30, 6, 20, tzinfo=KST))
        tasks.run_due(deps, datetime(2026, 9, 30, 12, 0, tzinfo=KST))
        self.assertEqual(self.collect.call_count, 1)
        self.assertTrue(self.client.entered and self.client.exited)
        self.assertEqual(WorkerState.get('bnk_fail_streak'), 0)

    def test_off_skips(self, *_):
        WorkerState.put('bnk_mode', 'off')
        tasks.run_due(Deps(), datetime(2026, 9, 30, 7, 0, tzinfo=KST))
        self.collect.assert_not_called()

    def test_rejected_login_stops_auto_login_until_switched_on_again(self, *_):
        from marketing import bnk
        self.factory.side_effect = bnk.BnkLoginError('출판유통통합전산망 로그인 실패: 비밀번호가 맞지 않습니다')
        deps = Deps()
        for day in (28, 29, 30):
            tasks.run_due(deps, datetime(2026, 9, day, 6, 20, tzinfo=KST))
        self.assertEqual(self.factory.call_count, 1)   # 계정이 잠기지 않게 한 번만 시도
        queued = WorkerState.get(tasks.ADMIN_QUEUE)
        self.assertEqual(len([q for q in queued if '자동 로그인을 멈췄어요' in q]), 1)
        self.assertIn('비밀번호가 맞지 않습니다', ''.join(queued))
        self.assertEqual(WorkerState.get('bnk_login_blocked'), '2026-09-28')
        self.assertEqual(deps.bot.notes, [])

    def test_monthly_waits_until_the_month_is_fully_read(self, *_):
        WorkerState.put('monthly_mode', 'live')
        deps = Deps()
        with mock.patch('marketing.tasks.bnk_sales.month_ready', return_value=False), \
                mock.patch('marketing.tasks.monthly.build') as build:
            tasks.run_due(deps, datetime(2026, 10, 3, 10, 0, tzinfo=KST))
        build.assert_not_called()
        self.assertIsNone(WorkerState.get('bnk_last_monthly'))

    def test_monthly_review_goes_to_the_review_room_on_the_third_after_0930_once(self, *_):
        WorkerState.put('monthly_mode', 'live')
        deps = Deps()
        with mock.patch('marketing.tasks.monthly.build', return_value='<b>📅 9월 돌아보기</b>') as build, \
                mock.patch('marketing.tasks.bnk_sales.month_ready', return_value=True):
            tasks.run_due(deps, datetime(2026, 10, 2, 10, 0, tzinfo=KST))
            tasks.run_due(deps, datetime(2026, 10, 3, 9, 29, tzinfo=KST))
            build.assert_not_called()
            tasks.run_due(deps, datetime(2026, 10, 3, 9, 30, tzinfo=KST))
            tasks.run_due(deps, datetime(2026, 10, 4, 10, 0, tzinfo=KST))
        self.assertEqual(build.call_count, 1)
        self.assertEqual(build.call_args[0][2], date(2026, 9, 1))
        sent = [c for c in deps.bot.tg.sent('send') if '돌아보기' in c['text']]
        self.assertEqual([(c['chat'], c['html']) for c in sent], [(-200, True)])
        self.assertEqual(WorkerState.get('bnk_last_monthly'), '2026-09')
        self.assertEqual(deps.bot.notes, [])

    def test_monthly_failure_is_retried_the_next_day_not_lost(self, *_):
        WorkerState.put('monthly_mode', 'live')
        deps = Deps()
        with mock.patch('marketing.tasks.monthly.build', side_effect=[RuntimeError('sidecar'), '<b>📅 9월 돌아보기</b>']) as build, \
                mock.patch('marketing.tasks.bnk_sales.month_ready', return_value=True):
            tasks.run_due(deps, datetime(2026, 10, 3, 9, 30, tzinfo=KST))
            tasks.run_due(deps, datetime(2026, 10, 3, 12, 0, tzinfo=KST))   # 같은 날은 다시 하지 않는다
            self.assertIsNone(WorkerState.get('bnk_last_monthly'))
            tasks.run_due(deps, datetime(2026, 10, 4, 9, 30, tzinfo=KST))
        self.assertEqual(build.call_count, 2)
        self.assertEqual(len([n for n in deps.bot.notes if 'monthly' in n]), 1)
        self.assertEqual([c['chat'] for c in deps.bot.tg.sent('send') if '돌아보기' in c['text']], [-200])
        self.assertEqual(WorkerState.get('bnk_last_monthly'), '2026-09')

    def test_monthly_goes_without_the_site_lines_when_the_site_is_down(self, *_):
        from marketing import bnk
        WorkerState.put('monthly_mode', 'live')
        WorkerState.put('bnk_last_run', '2026-10-03')
        self.factory.side_effect = bnk.BnkError('점검 중')
        deps = Deps()
        with mock.patch('marketing.tasks.monthly.build', return_value='<b>📅 9월 돌아보기</b>') as build, \
                mock.patch('marketing.tasks.bnk_sales.month_ready', return_value=True), self.assertLogs('intake', 'WARNING'):
            tasks.run_due(deps, datetime(2026, 10, 3, 9, 30, tzinfo=KST))
        self.assertIsNone(build.call_args[0][1])
        self.assertEqual([c['chat'] for c in deps.bot.tg.sent('send') if '돌아보기' in c['text']], [-200])
        self.assertEqual(WorkerState.get('bnk_last_monthly'), '2026-09')

    def test_monthly_login_rejection_stops_auto_login_and_keeps_the_month(self, *_):
        from marketing import bnk, bnk_sales
        WorkerState.put('monthly_mode', 'live')
        self.factory.side_effect = bnk.BnkLoginError('비밀번호가 맞지 않습니다')
        deps = Deps()
        with mock.patch('marketing.tasks.monthly.build', return_value='<b>📅 9월 돌아보기</b>') as build, \
                mock.patch('marketing.tasks.bnk_sales.month_ready', return_value=True):
            tasks.run_due(deps, datetime(2026, 10, 3, 9, 30, tzinfo=KST))   # 수집이 먼저 거부되면 같은 바퀴에 다시 로그인하지 않는다
            self.assertEqual(self.factory.call_count, 1)
            WorkerState.put('bnk_last_run', '2026-10-04')
            bnk_sales.unblock()
            tasks.run_due(deps, datetime(2026, 10, 4, 9, 30, tzinfo=KST))   # 월간 로그인 자체가 거부됨
        build.assert_not_called()
        self.assertEqual(self.factory.call_count, 2)
        self.assertEqual(WorkerState.get('bnk_login_blocked'), '2026-10-04')
        self.assertIsNone(WorkerState.get('bnk_last_monthly'))

    def test_a_month_that_never_gets_fully_read_is_reported_once(self, *_):
        WorkerState.put('monthly_mode', 'live')
        deps = Deps()
        with mock.patch('marketing.tasks.bnk_sales.missing_days', return_value=[date(2026, 9, 12), date(2026, 9, 13)]), \
                mock.patch('marketing.tasks.monthly.build') as build:
            tasks.run_due(deps, datetime(2026, 10, 4, 10, 0, tzinfo=KST))
            self.assertEqual(deps.bot.notes, [])
            tasks.run_due(deps, datetime(2026, 10, 5, 10, 0, tzinfo=KST))
            tasks.run_due(deps, datetime(2026, 10, 6, 10, 0, tzinfo=KST))
        build.assert_not_called()
        self.assertEqual(len(deps.bot.notes), 1)
        self.assertIn('9/12, 9/13', deps.bot.notes[0])

    def test_monthly_admin_only_goes_to_the_admin_and_off_sends_nothing(self, *_):
        with mock.patch('marketing.tasks.monthly.build', return_value='<b>📅 9월 돌아보기</b>') as build, \
                mock.patch('marketing.tasks.bnk_sales.month_ready', return_value=True):
            off = Deps()
            tasks.run_due(off, datetime(2026, 10, 3, 9, 30, tzinfo=KST))
            build.assert_not_called()
            self.assertIsNone(WorkerState.get('bnk_last_monthly'))
            WorkerState.put('monthly_mode', 'admin_only')
            admin = Deps()
            tasks.run_due(admin, datetime(2026, 10, 3, 9, 31, tzinfo=KST))
        self.assertEqual([c['chat'] for c in admin.bot.tg.sent('send') if '돌아보기' in c['text']], [100])
