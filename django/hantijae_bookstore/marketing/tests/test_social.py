import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings

from intake.models import WorkerState
from marketing import social
from marketing.apify import ApifyAuthError
from marketing.models import SocialPost, SocialRun
from marketing.tests.fakes import SOCIAL_ACCOUNTS, FakeApify, FakeLLM, fb_item, ig_item, make_post
from marketing.timeutil import KST

NOW = datetime(2026, 9, 30, 6, 20, tzinfo=KST)
SETTINGS = {'APIFY_TOKEN': 'tok', 'SOCIAL_ACCOUNTS': json.dumps(SOCIAL_ACCOUNTS)}


def iso(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def make_run(platform='facebook', accounts=('editor', 'ceo'), limit=5, purpose='normal', **extra):
    return SocialRun.objects.create(platform=platform, accounts=list(accounts), limit=limit, purpose=purpose,
                                    cap_usd=extra.pop('cap_usd', Decimal('0.15')), started_at=extra.pop('started_at', NOW),
                                    state=extra.pop('state', SocialRun.RUNNING), **extra)


@override_settings(MARKETING=SETTINGS)
class StoreTest(TestCase):
    def test_first_run_stores_posts_and_marks_accounts_ok(self):
        run = make_run(limit=20, purpose='first')
        items = [fb_item('1', text='새 글', time=iso(NOW - timedelta(days=1))),
                 fb_item('2', text='옛 글', time=iso(NOW - timedelta(days=40))),
                 fb_item('3', account='ceo.test', text='대표 글', time=iso(NOW - timedelta(days=2)))]
        new = social.store(run, items, SOCIAL_ACCOUNTS, NOW)
        self.assertEqual(sorted(p.post_id for p in new), ['1', '2', '3'])
        run.refresh_from_db()
        self.assertEqual(run.state, SocialRun.SUCCEEDED)
        self.assertEqual(run.stats['editor'], {'items': 2, 'valid': 2, 'errors': 0, 'new': 2, 'known': 0,
                                               'reached': True, 'gap': False, 'status': 'ok'})
        old = SocialPost.objects.get(post_id='2')
        self.assertEqual((old.verdict, old.judged_at), ({'baseline': True}, NOW))
        self.assertIsNone(SocialPost.objects.get(post_id='1').judged_at)
        self.assertEqual(set(WorkerState.get(social.OK_KEY)), {'facebook:editor', 'facebook:ceo'})

    def test_empty_account_is_a_failure_not_quiet(self):
        run = make_run()
        social.store(run, [fb_item('1', text='a', time=iso(NOW))], SOCIAL_ACCOUNTS, NOW)
        run.refresh_from_db()
        self.assertEqual(run.stats['ceo']['status'], 'empty')
        self.assertEqual(set(WorkerState.get(social.OK_KEY)), {'facebook:editor'})

    def test_all_new_full_page_is_a_gap(self):
        make_post('old', posted_at=NOW - timedelta(days=5))
        run = make_run(accounts=('editor',), limit=2)
        items = [fb_item('n1', text='a', time=iso(NOW - timedelta(days=1))),
                 fb_item('n2', text='b', time=iso(NOW - timedelta(days=2)))]
        social.store(run, items, SOCIAL_ACCOUNTS, NOW)
        run.refresh_from_db()
        self.assertEqual((run.stats['editor']['reached'], run.stats['editor']['gap']), (False, True))

    def test_fewer_than_limit_or_known_post_is_reached(self):
        make_post('old', posted_at=NOW - timedelta(days=5))
        run = make_run(accounts=('editor',), limit=5)
        social.store(run, [fb_item('n1', text='a', time=iso(NOW))], SOCIAL_ACCOUNTS, NOW)
        run2 = make_run(accounts=('editor',), limit=2)
        social.store(run2, [fb_item('n2', text='b', time=iso(NOW)), fb_item('old', text='', time=iso(NOW - timedelta(days=5)))],
                     SOCIAL_ACCOUNTS, NOW)
        for r in (run, run2):
            r.refresh_from_db()
            self.assertEqual((r.stats['editor']['reached'], r.stats['editor']['gap']), (True, False))

    def test_malformed_account(self):
        run = make_run(accounts=('editor',))
        social.store(run, [fb_item('', text='a'), fb_item('', text='b'), fb_item('9', text='c')], SOCIAL_ACCOUNTS, NOW)
        run.refresh_from_db()
        self.assertEqual(run.stats['editor']['status'], 'malformed')
        self.assertNotIn('facebook:editor', WorkerState.get(social.OK_KEY) or {})

    def test_known_posts_are_not_duplicated(self):
        make_post('1', posted_at=NOW - timedelta(days=1))
        run = make_run(accounts=('editor',))
        new = social.store(run, [fb_item('1', text='a', time=iso(NOW - timedelta(days=1)))], SOCIAL_ACCOUNTS, NOW)
        self.assertEqual(new, [])
        self.assertEqual(SocialPost.objects.count(), 1)
        self.assertEqual(SocialPost.objects.get().last_seen, NOW)

FB_ONLY = [{k: v for k, v in a.items() if k != 'instagram'} for a in SOCIAL_ACCOUNTS]


class Deps:
    def __init__(self, llm=None):
        self.notes = []
        self.bot = SimpleNamespace(notify_admin=self.notes.append)
        self.llm = llm or FakeLLM({'items': []})


def done(dataset='d1', cost=0.05, status='SUCCEEDED', run_id='r1'):
    return {'id': run_id, 'status': status, 'defaultDatasetId': dataset, 'usageTotalUsd': cost}


def both_accounts(prefix, when):
    return [fb_item(f'{prefix}e', text='편집장 글', time=iso(when)),
            fb_item(f'{prefix}c', account='ceo.test', text='대표 글', time=iso(when))]


@override_settings(MARKETING={'APIFY_TOKEN': 'tok', 'SOCIAL_ACCOUNTS': json.dumps(FB_ONLY)})
class RunTest(TestCase):
    def setUp(self):
        WorkerState.put(social.SWITCH_KEY, 'on')

    def seed_known(self):
        for role in ('editor', 'ceo'):
            make_post(f'k-{role}', account=role, posted_at=NOW - timedelta(days=3))

    def test_off_or_missing_config_makes_no_request(self):
        client = FakeApify()
        WorkerState.put(social.SWITCH_KEY, 'off')
        social.run_due(Deps(), NOW, client=client)
        WorkerState.put(social.SWITCH_KEY, 'on')
        with override_settings(MARKETING={'SOCIAL_ACCOUNTS': json.dumps(FB_ONLY)}):
            social.run_due(Deps(), NOW, client=client)
        self.assertEqual(client.started, [])
        self.assertFalse(SocialRun.objects.exists())

    def test_runs_after_0620_once_per_period_with_caps(self):
        client = FakeApify(starts=[done()], datasets={'d1': both_accounts('a', NOW - timedelta(hours=5))})
        social.run_due(Deps(), NOW - timedelta(minutes=1), client=client)
        self.assertEqual(client.started, [])
        social.run_due(Deps(), NOW, client=client)
        social.run_due(Deps(), NOW + timedelta(hours=6), client=client)
        [(actor, run_input, kw)] = client.started
        self.assertEqual(actor, 'apify~facebook-posts-scraper')
        self.assertEqual(run_input, {'startUrls': [{'url': 'https://www.facebook.com/editor.test'},
                                                   {'url': 'https://www.facebook.com/ceo.test/'}],
                                     'resultsLimit': 20, 'captionText': False})
        self.assertEqual(kw, {'timeout': 180, 'max_items': 40, 'max_charge_usd': 0.4, 'wait': 45})
        run = SocialRun.objects.get()
        self.assertEqual((run.purpose, run.state, run.cost_usd), ('first', 'succeeded', Decimal('0.050')))

    def test_running_run_is_polled_then_stored_with_cost(self):
        self.seed_known()
        client = FakeApify(starts=[{'id': 'r1', 'status': 'RUNNING', 'defaultDatasetId': 'd1'}],
                           polls=[{'id': 'r1', 'status': 'RUNNING'}, done(cost=0.052)],
                           datasets={'d1': both_accounts('a', NOW)})
        social.run_due(Deps(), NOW, client=client)
        self.assertEqual(SocialRun.objects.get().state, 'running')
        social.run_due(Deps(), NOW + timedelta(minutes=1), client=client)
        social.run_due(Deps(), NOW + timedelta(minutes=2), client=client)
        run = SocialRun.objects.get()
        self.assertEqual((run.purpose, run.state, run.cost_usd, run.limit), ('normal', 'succeeded', Decimal('0.052'), 5))
        self.assertEqual(SocialPost.objects.filter(first_run=run).count(), 2)

    def test_zero_items_retried_once_then_alerted_once(self):
        self.seed_known()
        client = FakeApify(starts=[done('d1'), done('d2')], datasets={'d1': [], 'd2': []})
        deps = Deps()
        social.run_due(deps, NOW, client=client)
        social.run_due(deps, NOW + timedelta(hours=1), client=client)
        self.assertEqual(len(client.started), 1)
        self.assertEqual(deps.notes, [])
        social.run_due(deps, NOW + timedelta(hours=2), client=client)
        social.run_due(deps, NOW + timedelta(hours=5), client=client)
        self.assertEqual(len(client.started), 2)
        self.assertEqual(len(deps.notes), 1)
        self.assertIn('오늘 페이스북(편집장·대표) 수집이 2번 모두 실패했어요', deps.notes[0])
        self.assertIn('편집장 0건', deps.notes[0])

    def test_gap_triggers_one_deep_run_for_that_account(self):
        self.seed_known()
        page = [fb_item(f'n{i}', text='새 글', time=iso(NOW - timedelta(hours=i + 1))) for i in range(5)]
        page.append(fb_item('k-ceo', account='ceo.test', text='', time=iso(NOW - timedelta(days=3))))
        deep = [fb_item('n9', text='더 옛 글', time=iso(NOW - timedelta(days=2)))]
        client = FakeApify(starts=[done('d1'), done('d2', run_id='r2')], datasets={'d1': page, 'd2': deep})
        deps = Deps()
        social.run_due(deps, NOW, client=client)
        social.run_due(deps, NOW + timedelta(minutes=1), client=client)
        social.run_due(deps, NOW + timedelta(hours=3), client=client)
        self.assertEqual(len(client.started), 2)
        deep_run = SocialRun.objects.get(purpose='deep')
        self.assertEqual((deep_run.accounts, deep_run.limit), (['editor'], 20))
        self.assertEqual(client.started[1][1]['startUrls'], [{'url': 'https://www.facebook.com/editor.test'}])
        self.assertEqual(deps.notes, [])  # 보충 실행에서 이어짐 확인(20건보다 적게 옴)

    def test_budget_stops_before_start(self):
        make_run(state='succeeded', cost_usd=Decimal('2.950'), started_at=NOW - timedelta(days=3))
        client, deps = FakeApify(), Deps()
        self.seed_known()
        social.run_due(deps, NOW, client=client)
        social.run_due(deps, NOW + timedelta(hours=3), client=client)
        self.assertEqual(client.started, [])
        self.assertEqual(SocialRun.objects.filter(state='skipped').count(), 2)
        self.assertEqual(len(deps.notes), 1)
        self.assertIn('예산', deps.notes[0])

    def test_auth_error_alerts_immediately(self):
        self.seed_known()
        client, deps = FakeApify(starts=[ApifyAuthError('HTTP 401')]), Deps()
        social.run_due(deps, NOW, client=client)
        run = SocialRun.objects.get()
        self.assertEqual((run.state, run.cost_usd), ('failed', Decimal('0')))
        self.assertTrue(any('APIFY_TOKEN' in n for n in deps.notes))

    def test_stuck_run_is_aborted_after_15_minutes(self):
        make_run(apify_run_id='r9', started_at=NOW - timedelta(minutes=16))
        self.seed_known()
        client = FakeApify(starts=[done('d1')], datasets={'d1': both_accounts('a', NOW)})
        social.run_due(Deps(), NOW, client=client)
        self.assertEqual(client.aborted, ['r9'])
        self.assertEqual(SocialRun.objects.get(apify_run_id='r9').state, 'failed')

    def test_failed_status_keeps_cost(self):
        self.seed_known()
        client = FakeApify(starts=[done(status='TIMED-OUT', cost=0.03)])
        social.run_due(Deps(), NOW, client=client)
        run = SocialRun.objects.get()
        self.assertEqual((run.state, run.cost_usd, run.error), ('failed', Decimal('0.030'), 'Apify TIMED-OUT'))

    def test_new_posts_are_judged(self):
        self.seed_known()
        client = FakeApify(starts=[done()], datasets={'d1': both_accounts('a', NOW)})
        with mock.patch('marketing.social.social_judge.judge_pending', return_value=[]) as judge:
            social.run_due(Deps(), NOW, client=client)
        judge.assert_called_once()
        self.assertEqual(judge.call_args[0][2], {'editor': '편집장', 'ceo': '대표'})


@override_settings(MARKETING=SETTINGS)
class InstagramRunTest(TestCase):
    def test_instagram_runs_once_a_week(self):
        WorkerState.put(social.SWITCH_KEY, 'on')
        for platform in ('facebook', 'instagram'):
            for role in ('editor', 'ceo'):
                make_post(f'{platform}-{role}', platform=platform, account=role, posted_at=NOW - timedelta(days=3))
        fb = both_accounts('a', NOW)
        ig = [ig_item('i1', owner='editor_ig', caption='글', ts=iso(NOW)), ig_item('i2', caption='글', ts=iso(NOW))]
        client = FakeApify(starts=[done('f1'), done('i1', run_id='r2'), done('f2', run_id='r3')],
                           datasets={'f1': fb, 'i1': ig, 'f2': both_accounts('b', NOW + timedelta(days=1))})
        monday = NOW - timedelta(days=2)  # 9/28(월)
        social.run_due(Deps(), monday, client=client)
        social.run_due(Deps(), monday + timedelta(days=1), client=client)
        self.assertEqual([a for a, _, _ in client.started], ['apify~facebook-posts-scraper',
                                                              'apify~instagram-post-scraper',
                                                              'apify~facebook-posts-scraper'])
        self.assertEqual(client.started[1][1], {'username': ['editor_ig', 'ceo_ig'], 'resultsLimit': 5,
                                                'dataDetailLevel': 'basicData', 'skipPinnedPosts': True})
