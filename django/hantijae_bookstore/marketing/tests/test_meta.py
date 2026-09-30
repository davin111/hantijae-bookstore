import hashlib
import hmac

import requests
from datetime import datetime, timezone

from django.test import SimpleTestCase, override_settings

from marketing import meta

CFG = {'META_PAGE_TOKEN': 'ptok', 'META_APP_SECRET': 'sec', 'META_PAGE_ID': '111', 'META_IG_USER_ID': '222'}
SINCE = datetime(2026, 9, 15, tzinfo=timezone.utc)


class FakeGet:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __call__(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        body = self.replies[url.rsplit('/', 2)[-2]]
        if isinstance(body, Exception):
            raise body
        status = body.pop('_status', 200) if isinstance(body, dict) else 200
        return type('R', (), {'status_code': status, 'json': lambda self: body})()


@override_settings(MARKETING=CFG)
class MetaTest(SimpleTestCase):
    def test_official_posts_use_appsecret_proof_and_filter_since(self):
        get = FakeGet({'111': {'data': [{'message': '북토크 안내', 'created_time': '2026-09-20T01:00:00+0000',
                                         'permalink_url': 'https://f/p1'}]},
                       '222': {'data': [{'caption': '새 책', 'timestamp': '2026-09-18T09:15:24+0000', 'permalink': 'https://i/1'},
                                        {'caption': '옛 글', 'timestamp': '2026-08-01T00:00:00+0000', 'permalink': 'https://i/0'}]}})
        out = meta.official_posts(SINCE, get=get)
        self.assertEqual([(p.channel, p.text, p.url) for p in out['facebook']], [('facebook', '북토크 안내', 'https://f/p1')])
        self.assertEqual([p.text for p in out['instagram']], ['새 책'])
        url, params = get.calls[0]
        self.assertEqual(url, 'https://graph.facebook.com/v26.0/111/posts')
        self.assertEqual(params['appsecret_proof'], hmac.new(b'sec', b'ptok', hashlib.sha256).hexdigest())
        self.assertEqual(params['since'], int(SINCE.timestamp()))

    def test_one_channel_failing_is_unknown(self):
        get = FakeGet({'111': RuntimeError('400'), '222': {'data': []}})
        self.assertEqual(meta.official_posts(SINCE, get=get), {'facebook': None, 'instagram': []})

    def test_missing_config_makes_no_request(self):
        get = FakeGet({})
        with override_settings(MARKETING={}):
            self.assertEqual(meta.official_posts(SINCE, get=get), {'facebook': None, 'instagram': None})
        self.assertEqual(get.calls, [])

    def test_errors_never_log_the_token(self):
        get = FakeGet({'111': {'_status': 400}, '222': requests.ConnectionError('url: /v26.0/222/media?access_token=ptok')})
        with self.assertLogs('intake', level='WARNING') as logs:
            self.assertEqual(meta.official_posts(SINCE, get=get), {'facebook': None, 'instagram': None})
        self.assertEqual(logs.output, ['WARNING:intake:meta facebook posts: HTTP 400',
                                       'WARNING:intake:meta instagram media: ConnectionError'])
        self.assertNotIn('ptok', ' '.join(logs.output))

    def test_official_posts_keep_post_ids(self):
        get = FakeGet({'111': {'data': [{'id': '111_9', 'message': '글', 'created_time': '2026-09-20T01:00:00+0000',
                                         'permalink_url': 'https://f/p1'}]},
                       '222': {'data': [{'id': '179', 'caption': '글', 'timestamp': '2026-09-18T09:15:24+0000',
                                         'permalink': 'https://i/1'}]}})
        out = meta.official_posts(SINCE, get=get)
        self.assertEqual((out['facebook'][0].id, out['instagram'][0].id), ('111_9', '179'))
        self.assertTrue(get.calls[0][1]['fields'].startswith('id,'))


class Reply:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        return self.body


@override_settings(MARKETING=CFG)
class PostCountsTest(SimpleTestCase):
    def test_facebook_reactions_comments_shares(self):
        calls = []

        def get(url, params=None, timeout=None):
            calls.append((url, params))
            return Reply(200, {'reactions': {'summary': {'total_count': 12}}, 'comments': {'summary': {'total_count': 3}},
                               'shares': {'count': 2}})
        self.assertEqual(meta.post_counts('facebook', '111_9', get=get), {'reactions': 12, 'comments': 3, 'shares': 2})
        self.assertEqual(calls[0][0], 'https://graph.facebook.com/v26.0/111_9')
        self.assertIn('appsecret_proof', calls[0][1])

    def test_facebook_without_shares_and_instagram(self):
        fb = lambda url, params=None, timeout=None: Reply(200, {'reactions': {'summary': {'total_count': 3}},  # noqa: E731
                                                                'comments': {'summary': {'total_count': 0}}})
        self.assertEqual(meta.post_counts('facebook', '111_9', get=fb), {'reactions': 3, 'comments': 0, 'shares': 0})
        ig = lambda url, params=None, timeout=None: Reply(200, {'like_count': 16, 'comments_count': 1})  # noqa: E731
        self.assertEqual(meta.post_counts('instagram', '179', get=ig), {'likes': 16, 'comments': 1})

    def test_failure_is_none_and_never_logs_the_token(self):
        def get(url, params=None, timeout=None):
            raise requests.ConnectionError(f'{url}?access_token=ptok')
        with self.assertLogs('intake', level='WARNING') as logs:
            self.assertIsNone(meta.post_counts('facebook', '111_9', get=get))
        self.assertNotIn('ptok', ' '.join(logs.output))
        self.assertIsNone(meta.post_counts('facebook', '', get=get))  # 번호 없으면 부르지 않는다

