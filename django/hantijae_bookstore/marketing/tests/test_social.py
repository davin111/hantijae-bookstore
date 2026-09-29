import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.test import TestCase, override_settings

from intake.models import WorkerState
from marketing import social
from marketing.models import SocialPost, SocialRun
from marketing.tests.fakes import SOCIAL_ACCOUNTS, fb_item, make_post
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
