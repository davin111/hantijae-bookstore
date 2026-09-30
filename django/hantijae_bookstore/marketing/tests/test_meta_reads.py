from datetime import datetime, timezone

from django.test import SimpleTestCase, override_settings

from marketing import meta

CFG = {'META_PAGE_TOKEN': 'ptok', 'META_APP_SECRET': 'sec', 'META_PAGE_ID': '111', 'META_IG_USER_ID': '222'}


class FakeGraph:
    """route(path, params) → (status, body). 부른 (경로, 파라미터)를 적는다."""

    def __init__(self, route):
        self.route, self.calls = route, []

    def __call__(self, url, params=None, timeout=None):
        path = url.split('/v26.0/', 1)[1]
        self.calls.append((path, params))
        status, body = self.route(path, params)
        return type('R', (), {'status_code': status, 'json': lambda self: body})()


def err(code):
    return 400, {'error': {'code': code, 'message': 'x', 'type': 'OAuthException'}}


TAGS = {'data': [{'id': '1', 'caption': '리브레리아Q 북클럽 『무궁화호를 위하여』', 'permalink': 'https://www.instagram.com/p/A/',
                  'timestamp': '2026-09-25T21:00:38+0000', 'username': 'librariaq', 'like_count': 17, 'comments_count': 2},
                 {'id': '2', 'caption': '주소 없는 글', 'timestamp': '2026-09-25T21:00:38+0000', 'username': 'x'}]}


@override_settings(MARKETING=CFG)
class ReadTest(SimpleTestCase):
    def test_tagged_media_reads_tags_with_proof(self):
        get = FakeGraph(lambda path, params: (200, TAGS))
        [m] = meta.tagged_media(get=get)   # 주소 없는 글은 버린다
        self.assertEqual((m.id, m.url, m.username, m.likes, m.comments),
                         ('1', 'https://www.instagram.com/p/A/', 'librariaq', 17, 2))
        self.assertEqual(m.posted_at, datetime(2026, 9, 25, 21, 0, 38, tzinfo=timezone.utc))
        path, params = get.calls[0]
        self.assertEqual(path, '222/tags')
        self.assertEqual(params['appsecret_proof'], meta.proof('ptok', 'sec'))
        self.assertIn('username', params['fields'])

    def test_business_media_returns_none_for_personal_accounts(self):
        get = FakeGraph(lambda path, params: err(110))
        self.assertIsNone(meta.business_media('someone', get=get))
        self.assertIsNone(meta.business_media('bad name}', get=get))   # 아이디 모양이 아니면 부르지도 않는다
        self.assertEqual(len(get.calls), 1)

    def test_business_media_reads_recent_posts(self):
        body = {'business_discovery': {'media': {'data': [
            {'id': '9', 'caption': '이번 주 입고 『커밍아웃 스토리』', 'permalink': 'https://www.instagram.com/p/B/',
             'timestamp': '2026-09-27T01:00:20+0000', 'like_count': 40, 'comments_count': 4}]}}}
        get = FakeGraph(lambda path, params: (200, body))
        [m] = meta.business_media('hagobooks', get=get)
        self.assertEqual((m.caption, m.username, m.likes), ('이번 주 입고 『커밍아웃 스토리』', '', 40))
        path, params = get.calls[0]
        self.assertEqual(path, '222')
        self.assertIn('business_discovery.username(hagobooks)', params['fields'])

    def test_auth_error_is_classified(self):
        get = FakeGraph(lambda path, params: err(190))
        with self.assertRaises(meta.MetaAuthError) as ctx:
            meta.tagged_media(get=get)
        self.assertEqual(ctx.exception.code, 190)
        self.assertNotIn('ptok', str(ctx.exception))
        with self.assertRaises(meta.MetaAuthError):
            meta.business_media('hagobooks', get=FakeGraph(lambda path, params: err(190)))
        with self.assertRaises(meta.MetaError) as other:
            meta.tagged_media(get=FakeGraph(lambda path, params: err(4)))   # 호출 한도 — 권한 문제 아님
        self.assertNotIsInstance(other.exception, meta.MetaAuthError)

    def test_channel_posts_reads_counts_in_one_call_per_channel(self):
        fb = {'data': [{'message': '굴삭기를 몰고 농사일을 도우면서도', 'created_time': '2026-09-24T05:42:25+0000',
                        'permalink_url': 'https://f/1', 'shares': {'count': 2},
                        'reactions': {'summary': {'total_count': 12}}, 'comments': {'summary': {'total_count': 3}}},
                       {'message': '범위 밖', 'created_time': '2026-09-29T05:00:00+0000', 'permalink_url': 'https://f/2'}]}
        ig = {'data': [{'caption': '2쇄를 찍었습니다', 'timestamp': '2026-09-23T03:47:57+0000',
                        'permalink': 'https://i/1', 'like_count': 21, 'comments_count': 1}]}
        get = FakeGraph(lambda path, params: (200, fb if path == '111/posts' else ig))
        since, until = datetime(2026, 9, 21, tzinfo=timezone.utc), datetime(2026, 9, 28, tzinfo=timezone.utc)
        got = meta.channel_posts(since, until, get=get)
        self.assertEqual([(p.reactions, p.comments, p.shares) for p in got['facebook']], [(12, 3, 2)])
        self.assertEqual([(p.channel, p.reactions, p.comments) for p in got['instagram']], [('instagram', 21, 1)])
        self.assertEqual(len(get.calls), 2)

    def test_channel_posts_marks_an_unreadable_channel_none(self):
        get = FakeGraph(lambda path, params: err(190) if path == '222/media' else (200, {'data': []}))
        with self.assertLogs('intake', level='WARNING'):
            got = meta.channel_posts(datetime(2026, 9, 21, tzinfo=timezone.utc), datetime(2026, 9, 28, tzinfo=timezone.utc),
                                     get=get)
        self.assertEqual(got, {'facebook': [], 'instagram': None})

    @override_settings(MARKETING={})
    def test_no_config_reads_nothing(self):
        get = FakeGraph(lambda path, params: (200, TAGS))
        self.assertEqual((meta.tagged_media(get=get), meta.business_media('hagobooks', get=get)), ([], None))
        self.assertEqual(get.calls, [])
