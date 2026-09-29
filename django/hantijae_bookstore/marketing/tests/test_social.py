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

    def test_same_post_in_both_accounts_or_twice_is_stored_once(self):
        run = make_run(limit=5)
        shared = fb_item('7', text='공동 글', time=iso(NOW))
        items = [shared, dict(shared), {**shared, 'inputUrl': 'https://www.facebook.com/ceo.test',
                                        'facebookUrl': 'https://www.facebook.com/ceo.test'}]
        new = social.store(run, items, SOCIAL_ACCOUNTS, NOW)
        self.assertEqual([p.post_id for p in new], ['7'])
        run.refresh_from_db()
        self.assertEqual((run.state, run.stats['ceo']['known'], run.stats['ceo']['status']), ('succeeded', 1, 'ok'))

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
        client = FakeApify(starts=[done('d1')], polls=[{'id': 'r9', 'status': 'RUNNING'}],
                           datasets={'d1': both_accounts('a', NOW)})
        social.run_due(Deps(), NOW, client=client)
        self.assertEqual(client.aborted, ['r9'])
        self.assertEqual(SocialRun.objects.get(apify_run_id='r9').state, 'failed')

    def test_late_check_keeps_an_already_finished_run(self):
        make_run(apify_run_id='r9', dataset_id='d9', started_at=NOW - timedelta(minutes=40))
        self.seed_known()
        client = FakeApify(polls=[done('d9', run_id='r9')], datasets={'d9': both_accounts('a', NOW)})
        social.run_due(Deps(), NOW, client=client)
        self.assertEqual(client.aborted, [])
        self.assertEqual(SocialRun.objects.get(apify_run_id='r9').state, 'succeeded')
        self.assertEqual(client.started, [])  # 두 계정 모두 받았으니 새 실행 없음

    def test_first_run_only_for_accounts_never_seen(self):
        make_post('k-ceo', account='ceo', posted_at=NOW - timedelta(days=3))
        client = FakeApify(starts=[done('d1'), done('d2', run_id='r2')],
                           datasets={'d1': [fb_item('e1', text='a', time=iso(NOW))],
                                     'd2': [fb_item('c1', account='ceo.test', text='b', time=iso(NOW))]})
        social.run_due(Deps(), NOW, client=client)
        social.run_due(Deps(), NOW + timedelta(minutes=1), client=client)
        self.assertEqual(len(client.started), 1)  # 첫 실행도 시도 한 번 → 다음은 2시간 뒤
        social.run_due(Deps(), NOW + timedelta(hours=2), client=client)
        self.assertEqual([(r.purpose, r.accounts, r.limit) for r in SocialRun.objects.order_by('id')],
                         [('first', ['editor'], 20), ('normal', ['ceo'], 5)])

    def test_account_that_had_a_first_run_goes_back_to_five(self):
        make_run(purpose='first', accounts=['editor', 'ceo'], limit=20, state='succeeded',
                 started_at=NOW - timedelta(days=1), stats={'editor': {'status': 'empty'}, 'ceo': {'status': 'empty'}})
        self.assertEqual(social.next_run('facebook', FB_ONLY, NOW), ('normal', ['editor', 'ceo'], 5))

    def test_result_processing_error_fails_the_run_instead_of_hanging(self):
        self.seed_known()

        class Broken(FakeApify):
            def dataset_items(self, dataset_id, limit=500):
                raise ValueError('bad json')
        client = Broken(starts=[done('d1')])
        social.run_due(Deps(), NOW, client=client)
        run = SocialRun.objects.get()
        self.assertEqual((run.state, run.error), ('failed', '결과 처리 실패: ValueError'))

    def test_judge_failure_keeps_the_run_and_alerts_once(self):
        self.seed_known()
        client = FakeApify(starts=[done()], datasets={'d1': both_accounts('a', NOW)})
        deps = Deps(llm=FakeLLM([]))  # 부르면 IndexError
        social.run_due(deps, NOW, client=client)
        self.assertEqual(SocialRun.objects.get().state, 'succeeded')
        self.assertEqual(SocialPost.objects.filter(judged_at__isnull=True).count(), 4)  # 미리 넣은 2건 + 새 글 2건
        self.assertEqual(len([n for n in deps.notes if '판정(LLM) 실패' in n]), 1)

    def test_switched_on_without_config_alerts_once_a_day(self):
        deps = Deps()
        with override_settings(MARKETING={'APIFY_TOKEN': 'tok', 'SOCIAL_ACCOUNTS': '[{broken'}):
            social.run_due(deps, NOW, client=FakeApify())
            social.run_due(deps, NOW + timedelta(hours=1), client=FakeApify())
        self.assertEqual(len(deps.notes), 1)
        self.assertIn('SOCIAL_ACCOUNTS', deps.notes[0])

    def test_failed_status_keeps_cost(self):
        self.seed_known()
        client = FakeApify(starts=[done(status='TIMED-OUT', cost=0.03)])
        social.run_due(Deps(), NOW, client=client)
        run = SocialRun.objects.get()
        self.assertEqual((run.state, run.cost_usd, run.error), ('failed', Decimal('0.030'), 'Apify TIMED-OUT'))

    def test_new_posts_are_judged(self):
        self.seed_known()
        client = FakeApify(starts=[done()], datasets={'d1': both_accounts('a', NOW)})
        with mock.patch('marketing.social.social_judge.judge_pending', return_value=[]) as judge_pending:
            social.run_due(Deps(), NOW, client=client)
        self.assertEqual(judge_pending.call_count, 2)  # 새 글이 들어온 직후 + 하루 한 번 점검(못 한 판정 다시)
        self.assertEqual(judge_pending.call_args_list[0][0][2], {'editor': '편집장', 'ceo': '대표'})


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


@override_settings(MARKETING=SETTINGS)
class UpkeepTest(TestCase):
    def test_stale_success_alerts_once_a_day(self):
        WorkerState.put(social.ON_SINCE_KEY, (NOW - timedelta(days=1)).isoformat())
        WorkerState.put(social.OK_KEY, {'facebook:editor': (NOW - timedelta(days=4)).isoformat(),
                                        'facebook:ceo': (NOW - timedelta(days=1)).isoformat()})
        deps = Deps()
        social.check_health(deps, SOCIAL_ACCOUNTS, NOW)
        social.check_health(deps, SOCIAL_ACCOUNTS, NOW + timedelta(hours=1))
        self.assertEqual(len(deps.notes), 1)
        self.assertIn('편집장 페이스북: 마지막 성공 09-26', deps.notes[0])
        self.assertNotIn('대표', deps.notes[0])
        self.assertNotIn('인스타', deps.notes[0])

    def test_prune_clears_text_by_relevance_and_deletes_old_rows(self):
        from marketing.models import Signal
        sig = Signal.objects.create(kind=Signal.SOCIAL, key='social:x', title='t', relevant=True)
        kw = {'text': '본문', 'shared': {'text': '원문'}, 'link': {'title': '링크'}}
        make_post('a', first_seen=NOW - timedelta(days=15), **kw)
        make_post('b', first_seen=NOW - timedelta(days=15), signal=sig, **kw)
        make_post('c', first_seen=NOW - timedelta(days=91), signal=sig, **kw)
        make_post('d', first_seen=NOW - timedelta(days=181), **kw)
        social.prune(NOW)
        got = {p.post_id: (p.text, p.shared, p.text_cleared_at is not None) for p in SocialPost.objects.all()}
        self.assertEqual(got, {'a': ('', {}, True), 'b': ('본문', {'text': '원문'}, False), 'c': ('', {}, True)})

    def test_switch_on_off_and_status_lines(self):
        self.assertEqual(social.switch('on', NOW), 'social=on')
        self.assertEqual(WorkerState.get(social.ON_SINCE_KEY), NOW.isoformat())
        make_run(state='succeeded', cost_usd=Decimal('0.052'), error='')
        lines = social.status_lines(NOW)
        self.assertEqual(lines[0], 'social=on')
        self.assertIn('social_month_usd=0.052/3.00', lines)
        self.assertEqual(social.switch('off', NOW), 'social=off')
        with override_settings(MARKETING={}):
            self.assertIn('social_missing=APIFY_TOKEN,SOCIAL_ACCOUNTS', social.status_lines(NOW))
        self.assertEqual(social.switch('', NOW).split('\n')[0], 'social=off')

    def test_daily_upkeep_runs_once_after_0620(self):
        WorkerState.put(social.SWITCH_KEY, 'on')
        with mock.patch('marketing.social.daily') as daily, mock.patch('marketing.social.next_run', return_value=None):
            social.run_due(Deps(), NOW - timedelta(minutes=1), client=FakeApify())
            social.run_due(Deps(), NOW, client=FakeApify())
            social.run_due(Deps(), NOW + timedelta(hours=2), client=FakeApify())
        daily.assert_called_once()
