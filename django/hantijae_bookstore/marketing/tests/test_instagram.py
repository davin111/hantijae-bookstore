from datetime import date, datetime, timezone
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
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
    """tags: 태그 글 목록, pros: 프로페셔널 아이디 → 최근 글 목록, auth: 모든 호출이 code 190,
    broken: 오류 날 아이디 — 집합이면 code 2, {아이디: code}면 그 code로."""

    def __init__(self, tags=(), pros=None, auth=False, broken=(), tags_broken=False):
        self.tags, self.pros, self.auth = list(tags), pros or {}, auth
        self.broken = dict(broken) if isinstance(broken, dict) else {h: 2 for h in broken}
        self.tags_broken, self.calls = tags_broken, []

    def __call__(self, url, params=None, timeout=None):
        path = url.split('/v26.0/', 1)[1]
        self.calls.append((path, params.get('fields', '')))
        if self.auth:
            return self._r(400, {'error': {'code': 190}})
        if path.endswith('/tags'):
            if self.tags_broken:
                return self._r(500, {'error': {'code': 2}})
            return self._r(200, {'data': self.tags})
        name = params['fields'].split('business_discovery.username(', 1)[1].split(')', 1)[0]
        if name in self.broken:
            return self._r(500, {'error': {'code': self.broken[name]}})
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

    def test_tagger_check_error_leaves_the_name_out(self):
        g = Graph(tags=[media('A', '『무궁화호를 위하여』 읽었다', date(2026, 9, 26), 'flaky.shop')], broken={'flaky.shop'})
        with self.assertLogs('intake', level='WARNING') as cm:
            instagram.run(self.deps(), TODAY, self.notes.append, get=g)
        s = Signal.objects.get()
        self.assertEqual(s.detail['where'], '')
        self.assertNotIn('flaky.shop', '\n'.join(cm.output))

    def test_handles_in_captions_are_masked(self):
        g = Graph(tags=[media('A', '@friend.personal 랑 『무궁화호를 위하여』 읽음', date(2026, 9, 26))])
        llm = FakeLLM(REVIEW)
        instagram.run(self.deps(llm), TODAY, self.notes.append, get=g)
        s = Signal.objects.get()
        self.assertIn('@…', s.title)
        self.assertNotIn('friend.personal', s.title)
        self.assertIn('@…', s.detail['snippet'])
        self.assertNotIn('friend.personal', s.detail['snippet'])
        self.assertNotIn('friend.personal', llm.calls[0][1])

    def test_tags_error_still_reads_partners_then_notifies(self):
        g = Graph(tags=[], pros={p: [] for p in instagram.PARTNERS}, tags_broken=True)
        g.pros['todakbook'] = [media('B', '『무궁화호를 위하여』 입고', date(2026, 10, 3))]
        with self.assertLogs('intake', level='WARNING'):
            instagram.run(self.deps(), SUNDAY, self.notes.append, get=g)
        s = Signal.objects.get()
        self.assertEqual(s.detail['where'], '@todakbook')
        self.assertEqual(len([n for n in self.notes if '인스타 태그 글을 읽지 못했어요' in n]), 1)

    def test_all_partners_failing_notifies_once(self):
        g = Graph(pros={p: [] for p in instagram.PARTNERS}, broken=set(instagram.PARTNERS))
        with self.assertLogs('intake', level='WARNING'):
            instagram.run(self.deps(), SUNDAY, self.notes.append, get=g)
        self.assertEqual(len([n for n in self.notes if '협력 계정' in n]), 1)

    def test_partner_code_10_is_skipped_not_treated_as_auth_error(self):
        pros = {p: [] for p in instagram.PARTNERS}
        pros['todakbook'] = [media('B', '『무궁화호를 위하여』 입고', date(2026, 10, 3))]
        g = Graph(pros=pros, broken={'hagobooks': 10})
        with self.assertLogs('intake', level='WARNING'):
            instagram.run(self.deps(), SUNDAY, self.notes.append, get=g)
        self.assertEqual(Signal.objects.get().detail['where'], '@todakbook')
        self.assertNotIn(instagram.AUTH_NOTE, self.notes)

    def test_tagger_code_200_is_not_treated_as_auth_error(self):
        g = Graph(tags=[media('A', '『무궁화호를 위하여』 읽었다', date(2026, 9, 26), 'flaky.shop')],
                  broken={'flaky.shop': 200})
        with self.assertLogs('intake', level='WARNING'):
            instagram.run(self.deps(), TODAY, self.notes.append, get=g)
        s = Signal.objects.get()
        self.assertEqual(s.detail['where'], '')
        self.assertNotIn(instagram.AUTH_NOTE, self.notes)

    @override_settings(MARKETING={**CFG, 'META_ACCESS_EXPIRES': '2026.12.28'})
    def test_bad_expiry_setting_falls_back_to_default(self):
        g = Graph(pros={p: [] for p in instagram.PARTNERS})   # 12-20은 일요일
        with self.assertLogs('intake', level='WARNING') as cm:
            instagram.run(self.deps(), date(2026, 12, 20), self.notes.append, get=g)
        self.assertIn('META_ACCESS_EXPIRES', '\n'.join(cm.output))
        self.assertEqual(len([n for n in self.notes if '12월 28일' in n]), 1)


class CommandTest(TestCase):
    def setUp(self):
        self.book = make_book(title='무궁화호를 위하여', subtitle='', published=date(2026, 3, 16),
                              isbn='979-11-00000-16-1', author='하승우')

    def fake_scan(self, today, partners=False, **kw):
        from marketing.review_filter import terms
        from marketing.review_search import Post
        Signal.objects.create(kind='review', key='review:x', book=self.book, title='기준선')
        post = Post('ig_tag', 'https://www.instagram.com/p/A/', '북클럽 이번 책', '『무궁화호를 위하여』', date(2026, 9, 26),
                    '@librariaq')
        return reviews.Report(books=1, found=1, baseline=1), [(terms(self.book), post, 'review:y')]

    def test_dry_run_rolls_back_and_prints(self):
        out = StringIO()
        with mock.patch('marketing.instagram.scan', side_effect=self.fake_scan) as scan, \
                mock.patch('intake.deps.build_deps', return_value=SimpleNamespace(llm=FakeLLM(REVIEW))):
            call_command('marketing_scan_instagram', '--dry-run', '--partners', stdout=out)
        self.assertTrue(scan.call_args.kwargs['partners'])
        text = out.getvalue()
        self.assertIn('새 글 1건(서평 1건), 기준선 1건, 읽지 못한 곳 없음', text)
        self.assertIn('『무궁화호를 위하여』 [인스타 태그 @librariaq] 북클럽 이번 책 | 2026-09-26 | review 읽은 감상', text)
        self.assertIn('(dry-run: 기록하지 않았어요)', text)
        self.assertEqual(Signal.objects.count(), 0)

    def test_no_judge_skips_the_llm(self):
        out = StringIO()
        with mock.patch('marketing.instagram.scan', side_effect=self.fake_scan), \
                mock.patch('intake.deps.build_deps') as build, mock.patch('marketing.reviews.save_judged') as judged:
            call_command('marketing_scan_instagram', '--dry-run', '--no-judge', stdout=out)
        build.assert_not_called()
        judged.assert_not_called()
        self.assertIn('| 판별 안 함 |', out.getvalue())
