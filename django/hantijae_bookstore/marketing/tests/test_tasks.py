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


class FakeBot:
    def __init__(self, mode):
        self.marketing, self.notes = FakeMarketing(mode), []

    def notify_admin(self, text):
        self.notes.append(text)


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

    def test_social_step_runs_every_loop_unless_off(self, *_):
        tasks.run_due(Deps(), datetime(2026, 9, 29, 3, 0, tzinfo=KST))
        tasks.run_due(Deps(), datetime(2026, 9, 29, 3, 1, tzinfo=KST))
        self.assertEqual(self.social_step.call_count, 2)
        tasks.run_due(Deps('off'), datetime(2026, 9, 29, 7, 0, tzinfo=KST))
        self.assertEqual(self.social_step.call_count, 2)

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

    def test_off_mode_skips_selection_scan(self, *_):
        tasks.run_due(Deps('off'), datetime(2026, 9, 29, 7, 0, tzinfo=KST))
        self.selection_scan.assert_not_called()
