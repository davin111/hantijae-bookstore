from datetime import date, datetime, timezone
from types import SimpleNamespace

from django.test import TestCase, override_settings

from intake.models import WorkerState
from marketing import instagram, meta, reviews
from marketing.models import Signal
from marketing.tests.fakes import FakeLLM, make_book

CFG = {'META_PAGE_TOKEN': 'ptok', 'META_APP_SECRET': 'sec', 'META_PAGE_ID': '111', 'META_IG_USER_ID': '222'}
TODAY = date(2026, 9, 30)   # 수요일
SUNDAY = date(2026, 10, 4)


def media(mid, caption, day, username='', url=None):
    return {'id': mid, 'caption': caption, 'permalink': url or f'https://www.instagram.com/p/{mid}/',
            'timestamp': f'{day.isoformat()}T03:00:00+0000', 'username': username, 'like_count': 3, 'comments_count': 0}


class Graph:
    """tags: 태그 글 목록, pros: 프로페셔널 아이디 → 최근 글 목록, auth: 모든 호출이 code 190, broken: 오류 날 아이디."""

    def __init__(self, tags=(), pros=None, auth=False, broken=()):
        self.tags, self.pros, self.auth, self.broken, self.calls = list(tags), pros or {}, auth, set(broken), []

    def __call__(self, url, params=None, timeout=None):
        path = url.split('/v26.0/', 1)[1]
        self.calls.append((path, params.get('fields', '')))
        if self.auth:
            return self._r(400, {'error': {'code': 190}})
        if path.endswith('/tags'):
            return self._r(200, {'data': self.tags})
        name = params['fields'].split('business_discovery.username(', 1)[1].split(')', 1)[0]
        if name in self.broken:
            return self._r(500, {'error': {'code': 2}})
        if name not in self.pros:
            return self._r(400, {'error': {'code': 110, 'error_subcode': 2207013}})
        return self._r(200, {'business_discovery': {'media': {'data': self.pros[name]}}})

    @staticmethod
    def _r(status, body):
        return type('R', (), {'status_code': status, 'json': lambda self: body})()


REVIEW = {'items': [{'id': 0, 'verdict': 'review', 'reason': '읽은 감상'}]}


@override_settings(MARKETING=CFG)
class InstagramTest(TestCase):
    def setUp(self):
        self.mu = make_book(title='무궁화호를 위하여', subtitle='', published=date(2026, 3, 16), isbn='979-11-00000-16-1',
                            author='하승우')
        self.co = make_book(title='커밍아웃 스토리', subtitle='', published=date(2018, 6, 11), isbn='979-11-00000-01-1',
                            author='성소수자부모모임')
        self.notes = []

    def deps(self, llm=None):
        return SimpleNamespace(llm=llm or FakeLLM(REVIEW))

    def test_fresh_tagged_post_is_judged_with_professional_name(self):
        g = Graph(tags=[media('A', '북클럽 이번 책 『무궁화호를 위하여』', date(2026, 9, 26), 'librariaq')],
                  pros={'librariaq': []})
        report = instagram.run(self.deps(), TODAY, self.notes.append, get=g)
        s = Signal.objects.get()
        self.assertEqual((s.book, s.relevant, s.detail['source'], s.detail['where']), (self.mu, True, 'ig_tag', '@librariaq'))
        self.assertEqual([x.pk for x in report.reviews], [s.pk])

    def test_personal_tagger_name_is_not_stored(self):
        g = Graph(tags=[media('A', '『무궁화호를 위하여』 읽었다', date(2026, 9, 26), 'my.private.name')])
        instagram.run(self.deps(), TODAY, self.notes.append, get=g)
        s = Signal.objects.get()
        self.assertEqual(s.detail['where'], '')
        self.assertNotIn('my.private.name', str(s.detail) + s.title + s.url)

    def test_old_tagged_posts_are_baseline(self):
        llm = FakeLLM(REVIEW)
        g = Graph(tags=[media('A', '『무궁화호를 위하여』', date(2026, 1, 4), 'someone')])
        instagram.run(self.deps(llm), TODAY, self.notes.append, get=g)
        self.assertEqual((Signal.objects.get().detail['verdict'], llm.calls), ('old', []))
        self.assertEqual([c for c in g.calls if 'business_discovery' in c[1]], [])   # 기준선 글은 글쓴이를 확인하지 않는다

    def test_post_about_two_books_makes_two_signals(self):
        llm = FakeLLM({'items': [{'id': 0, 'verdict': 'review'}, {'id': 1, 'verdict': 'review'}]})
        g = Graph(tags=[media('A', '『무궁화호를 위하여』와 『커밍아웃 스토리』', date(2026, 9, 26))])
        instagram.run(self.deps(llm), TODAY, self.notes.append, get=g)
        self.assertEqual({s.book for s in Signal.objects.all()}, {self.mu, self.co})

    def test_short_titles_are_not_matched(self):
        make_book(title='밥', subtitle='', published=date(2020, 1, 1), isbn='979-11-00000-99-9', author=None)
        g = Graph(tags=[media('A', '오늘 밥 먹고 책 읽기', date(2026, 9, 26))])
        instagram.run(self.deps(), TODAY, self.notes.append, get=g)
        self.assertEqual(Signal.objects.count(), 0)

    def test_partners_only_on_sunday(self):
        g = Graph(pros={p: [] for p in instagram.PARTNERS})
        instagram.run(self.deps(), TODAY, self.notes.append, get=g)
        self.assertEqual([c for c in g.calls if 'business_discovery' in c[1]], [])
        instagram.run(self.deps(), SUNDAY, self.notes.append, get=g)
        self.assertEqual(len([c for c in g.calls if 'business_discovery' in c[1]]), len(instagram.PARTNERS))

    def test_same_post_from_tags_and_partner_is_one_signal(self):
        post = media('A', '입고 『커밍아웃 스토리』', date(2026, 10, 2), 'hagobooks')
        pros = {p: [] for p in instagram.PARTNERS}
        pros['hagobooks'] = [dict(post, username='')]
        g = Graph(tags=[post], pros=pros)
        llm = FakeLLM(REVIEW)
        instagram.run(self.deps(llm), SUNDAY, self.notes.append, get=g)
        s = Signal.objects.get()
        self.assertEqual((s.detail['source'], s.detail['where']), ('ig_tag', '@hagobooks'))
        self.assertEqual(llm.calls[0][1].count('한티재 책:'), 1)

    def test_one_partner_failing_skips_only_that_partner(self):
        pros = {p: [] for p in instagram.PARTNERS}
        pros['todakbook'] = [media('B', '『무궁화호를 위하여』 입고', date(2026, 10, 3))]
        g = Graph(pros=pros, broken={'hagobooks'})
        with self.assertLogs('intake', level='WARNING'):
            instagram.run(self.deps(), SUNDAY, self.notes.append, get=g)
        self.assertEqual(Signal.objects.get().detail['where'], '@todakbook')

    def test_auth_error_alerts_once_a_day(self):
        g = Graph(auth=True)
        self.assertIsNone(instagram.run(self.deps(), TODAY, self.notes.append, get=g))
        instagram.run(self.deps(), TODAY, self.notes.append, get=g)
        self.assertEqual(self.notes, [instagram.AUTH_NOTE])
        instagram.run(self.deps(), date(2026, 10, 1), self.notes.append, get=g)
        self.assertEqual(len(self.notes), 2)

    def test_expiry_reminder_once_from_eight_days_before(self):
        g = Graph(pros={p: [] for p in instagram.PARTNERS})   # 12-20은 일요일
        instagram.run(self.deps(), date(2026, 12, 19), self.notes.append, get=g)
        self.assertEqual(self.notes, [])
        instagram.run(self.deps(), date(2026, 12, 20), self.notes.append, get=g)
        instagram.run(self.deps(), date(2026, 12, 21), self.notes.append, get=g)
        self.assertEqual(len([n for n in self.notes if '12월 28일' in n]), 1)

    @override_settings(MARKETING={**CFG, 'META_ACCESS_EXPIRES': '2027-03-28'})
    def test_expiry_date_comes_from_settings(self):
        instagram.run(self.deps(), date(2026, 12, 20), self.notes.append, get=Graph(pros={p: [] for p in instagram.PARTNERS}))
        self.assertEqual(self.notes, [])

    @override_settings(MARKETING={})
    def test_without_meta_config_does_nothing(self):
        g = Graph()
        self.assertEqual(instagram.run(self.deps(), date(2026, 12, 20), self.notes.append, get=g).found, 0)
        self.assertEqual((g.calls, self.notes), ([], []))
