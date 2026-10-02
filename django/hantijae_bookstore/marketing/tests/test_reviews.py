import json
import urllib.parse
from datetime import date
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from intake.models import WorkerState
from marketing import reviews
from marketing.models import Signal
from marketing.review_filter import terms
from marketing.review_search import Post
from marketing.tests.fakes import FakeLLM, make_book


class FlakyLLM:
    """처음 fail_first번은 예외, 그다음은 reply를 돌려준다."""

    def __init__(self, fail_first, reply=None):
        self.left, self.reply, self.calls = fail_first, reply or {'items': []}, []

    def complete(self, system, user, attachments=()):
        self.calls.append((system, user))
        if self.left:
            self.left -= 1
            raise RuntimeError('sidecar down')
        return json.dumps(self.reply, ensure_ascii=False)


class JudgeTest(TestCase):
    def setUp(self):
        self.t = terms(make_book(title='무궁화호를 위하여', subtitle='변경의 정치', published=date(2026, 3, 16),
                                 isbn='979-11-00000-16-1', author='하승우'))

    def post(self, n, day=date(2026, 9, 25)):
        return Post('naver_blog', f'https://blog.naver.com/a/{n}', f'무궁화호를 위하여 읽고 {n}', '요약 ' * 80, day)

    def test_maps_verdicts_by_row_and_skips_bad_ones(self):
        llm = FakeLLM({'items': [{'id': 0, 'verdict': 'review', 'reason': '감상'}, {'id': '1', 'verdict': 'promo', 'reason': '판매'},
                                 {'id': 2, 'verdict': '모름'}, {'id': 9, 'verdict': 'review'}, 'x']})
        out = reviews.judge(llm, [(self.t, self.post(i)) for i in range(3)])
        self.assertEqual(out, {0: ('review', '감상'), 1: ('promo', '판매')})
        _, user = llm.calls[0]
        self.assertIn('『무궁화호를 위하여』 ― 변경의 정치 (지은이: 하승우)', user)
        self.assertIn('[네이버 블로그]', user)
        self.assertNotIn('https://', user)   # 주소는 판별에 보내지 않는다

    def test_rows_are_sent_in_batches_of_forty(self):
        llm = FakeLLM([{'items': [{'id': 39, 'verdict': 'review'}]}, {'items': [{'id': 0, 'verdict': 'unrelated'}]}])
        out = reviews.judge(llm, [(self.t, self.post(i)) for i in range(41)])
        self.assertEqual(out, {39: ('review', ''), 40: ('unrelated', '')})
        self.assertEqual(len(llm.calls), 2)

    def test_one_failed_batch_is_skipped(self):
        llm = FlakyLLM(fail_first=1, reply={'items': [{'id': 0, 'verdict': 'review'}]})
        with self.assertLogs('intake', level='WARNING'):
            out = reviews.judge(llm, [(self.t, self.post(i)) for i in range(41)])
        self.assertEqual(out, {40: ('review', '')})

    def test_every_batch_failing_raises(self):
        with self.assertLogs('intake', level='WARNING'), self.assertRaises(RuntimeError):
            reviews.judge(FlakyLLM(fail_first=9), [(self.t, self.post(0))])

    def test_dateless_post_says_date_unknown(self):
        llm = FakeLLM({'items': []})
        reviews.judge(llm, [(self.t, self.post(0, day=None))])
        self.assertIn('날짜 모름', llm.calls[0][1])


CFG = {'NAVER_HUB_CLIENT_ID': 'nid', 'NAVER_HUB_CLIENT_SECRET': 'nsec', 'KAKAO_REST_API_KEY': 'kk'}
TODAY = date(2026, 9, 30)


def no_sleep(_):
    pass


def nb(title, link, desc, postdate):
    return {'title': title, 'link': link, 'description': desc, 'bloggername': '별명', 'bloggerlink': 'x', 'postdate': postdate}


def nc(title, link, desc, cafename='독서모임'):
    return {'title': title, 'link': link, 'description': desc, 'cafename': cafename, 'cafeurl': 'x'}


def kd(title, url, contents, dt, cafename=None):
    d = {'title': title, 'url': url, 'contents': contents, 'datetime': dt, 'blogname': '별명', 'thumbnail': ''}
    if cafename:
        d['cafename'] = cafename
    return d


class FakeAPI:
    """출처별로 돌려줄 결과(질의는 보지 않는다). raise_for에 든 출처 호출은 실패한다.
    raise_query: {(출처, 글자)} — 그 출처 호출의 질의(query 파라미터)에 그 글자가 들어 있으면 실패한다."""

    def __init__(self, naver_blog=(), naver_cafe=(), daum_blog=(), daum_cafe=(), raise_for=(), raise_query=()):
        self.data = {'naver_blog': list(naver_blog), 'naver_cafe': list(naver_cafe), 'daum_blog': list(daum_blog),
                     'daum_cafe': list(daum_cafe)}
        self.raise_for, self.raise_query, self.calls = set(raise_for), set(raise_query), []

    def __call__(self, url, headers):
        source = ('naver_' if 'naverapihub' in url else 'daum_') + ('cafe' if '/cafe' in url else 'blog')
        self.calls.append(source)
        if source in self.raise_for:
            raise RuntimeError('429 Too Many Requests')
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['query'][0]
        if any(s == source and text in query for s, text in self.raise_query):
            raise RuntimeError('429 Too Many Requests')
        items = self.data[source]
        return {'items': items} if source.startswith('naver') else {'documents': items}


REVIEW = {'items': [{'id': 0, 'verdict': 'review', 'reason': '읽은 감상'}]}


class ScanTest(TestCase):
    def setUp(self):
        self.book = make_book(title='커밍아웃 스토리', subtitle='성소수자와 그 부모들의 이야기', published=date(2018, 6, 11),
                              isbn='979-11-00000-01-1', author='성소수자부모모임')

    def scan(self, api, llm=None, cfg=CFG, books=None, sleep=no_sleep):
        report, fresh = reviews.scan(TODAY, books=books or [self.book], cfg=cfg, get_json=api, sleep=sleep)
        if llm is not None:
            reviews.save_judged(llm, fresh, report)
        return report, fresh

    def test_fresh_review_is_judged_and_old_post_is_baseline(self):
        api = FakeAPI(naver_blog=[nb('<b>커밍아웃 스토리</b> 독후감', 'https://blog.naver.com/a/1', '한티재 읽고', '20260925'),
                                  nb('<b>커밍아웃 스토리</b> 독후감', 'https://blog.naver.com/a/0', '한티재 읽고', '20260101')])
        llm = FakeLLM(REVIEW)
        report, _ = self.scan(api, llm)
        new, old = Signal.objects.get(url='https://blog.naver.com/a/1'), Signal.objects.get(url='https://blog.naver.com/a/0')
        self.assertEqual((new.kind, new.relevant, new.book, new.happens_on), ('review', True, self.book, date(2026, 9, 25)))
        self.assertEqual(new.detail, {'source': 'naver_blog', 'where': '', 'snippet': '한티재 읽고', 'verdict': 'review',
                                      'reason': '읽은 감상'})
        self.assertNotIn('별명', json.dumps(new.detail, ensure_ascii=False))   # 블로거 별명은 적지 않는다
        self.assertEqual((old.relevant, old.detail['verdict']), (False, 'old'))
        self.assertEqual(llm.calls[0][1].count('한티재 책:'), 1)
        self.assertEqual((report.books, report.found, report.baseline, report.reviews), (1, 1, 1, [new]))
        self.assertEqual(report.verdicts[new.key], ('review', '읽은 감상'))

    def test_same_post_from_two_sources_is_one_signal(self):
        api = FakeAPI(naver_blog=[nb('커밍아웃 스토리(5)', 'https://blog.naver.com/life/224', '한티재', '20260925')],
                      daum_blog=[kd('커밍아웃 스토리(5)', 'http://m.blog.naver.com/life/224/', '한티재', '2026-09-25T10:00:00.000+09:00')])
        llm = FakeLLM(REVIEW)
        self.scan(api, llm)
        self.assertEqual(Signal.objects.filter(kind='review').count(), 1)
        self.assertEqual(llm.calls[0][1].count('한티재 책:'), 1)

    def test_noise_never_reaches_the_llm(self):
        naeran = make_book(title='내란 앞에서', subtitle='', published=date(2026, 7, 17), isbn='979-11-00000-02-8', author='김해원')
        api = FakeAPI(naver_blog=[nb('내란 앞에서 국민은', 'https://blog.naver.com/n/1', '헌법재판소 앞에서', '20260928'),
                                  nb('<b>내란</b> 사태', 'https://blog.naver.com/n/2', '앞에서 시민들', '20260928'),
                                  nb('내란 앞에서', 'https://blog.naver.com/n/3', '김해원 교수의 일지', '20260928')])
        llm = FakeLLM({'items': [{'id': 0, 'verdict': 'review'}]})
        self.scan(api, llm, books=[naeran])
        self.assertEqual(llm.calls[0][1].count('한티재 책:'), 1)
        self.assertIn('김해원 교수의 일지', llm.calls[0][1])
        self.assertEqual(list(Signal.objects.values_list('url', flat=True)), ['https://blog.naver.com/n/3'])

    def test_dateless_cafe_posts_are_baseline_on_first_search(self):
        first = FakeAPI(naver_cafe=[nc('모임 후기', 'https://cafe.naver.com/c/1', '&lt;커밍아웃 스토리&gt; 읽기')])
        llm = FakeLLM(REVIEW)
        report, fresh = self.scan(first, llm)
        self.assertEqual((report.baseline, fresh, llm.calls), (1, [], []))
        self.assertEqual(Signal.objects.get().detail['verdict'], 'old')
        self.assertIn(f'{self.book.id}:naver_cafe', WorkerState.get(reviews.SCANNED))
        later = FakeAPI(naver_cafe=[nc('모임 후기', 'https://cafe.naver.com/c/1', '&lt;커밍아웃 스토리&gt; 읽기'),
                                    nc('새 모임 후기', 'https://cafe.naver.com/c/2', '&lt;커밍아웃 스토리&gt; 읽기')])
        self.scan(later, llm)
        self.assertEqual(Signal.objects.get(url='https://cafe.naver.com/c/2').detail['verdict'], 'review')
        self.assertEqual(Signal.objects.get(url='https://cafe.naver.com/c/2').detail['where'], '독서모임')

    def test_failing_source_is_reported_and_others_continue(self):
        api = FakeAPI(naver_blog=[nb('커밍아웃 스토리 독후감', 'https://blog.naver.com/a/1', '한티재', '20260925')],
                      raise_for={'daum_blog'})
        with self.assertLogs('intake', level='WARNING') as logs:
            report, fresh = self.scan(api)
        self.assertEqual((report.failed, len(fresh)), (['daum_blog'], 1))
        self.assertEqual(len([r for r in logs.records if 'daum_blog' in r.getMessage()]), 1)   # 출처마다 한 번만 남긴다

    def test_one_failed_query_keeps_the_source_unsearched(self):
        with self.assertLogs('intake', level='WARNING'):
            self.scan(FakeAPI(naver_cafe=[], raise_query={('naver_cafe', '성소수자부모모임')}))
        scanned = WorkerState.get(reviews.SCANNED) or []
        self.assertNotIn(f'{self.book.id}:naver_cafe', scanned)
        self.assertIn(f'{self.book.id}:naver_blog', scanned)
        llm = FakeLLM(REVIEW)
        _, fresh = self.scan(FakeAPI(naver_cafe=[nc('옛 모임 후기', 'https://cafe.naver.com/c/9', '&lt;커밍아웃 스토리&gt; 읽기')]), llm)
        self.assertEqual((fresh, llm.calls), ([], []))
        self.assertEqual(Signal.objects.get(url='https://cafe.naver.com/c/9').detail['verdict'], 'old')

    def test_missing_kakao_key_skips_daum_sources(self):
        api = FakeAPI()
        report, _ = self.scan(api, cfg={'NAVER_HUB_CLIENT_ID': 'n', 'NAVER_HUB_CLIENT_SECRET': 's'})
        self.assertEqual((set(api.calls), report.failed), ({'naver_blog', 'naver_cafe'}, []))

    def test_no_keys_does_nothing(self):
        api = FakeAPI()
        report, fresh = self.scan(api, cfg={})
        self.assertEqual((api.calls, report.books, fresh), ([], 0, []))

    def test_known_post_is_not_judged_again(self):
        post = Post('naver_blog', 'https://blog.naver.com/a/1', 'x', '', date(2026, 9, 25))
        Signal.objects.create(kind='review', key=reviews.signal_key(self.book, post), book=self.book, title='x')
        api = FakeAPI(naver_blog=[nb('커밍아웃 스토리 독후감', 'https://m.blog.naver.com/a/1', '한티재', '20260925')])
        _, fresh = self.scan(api)
        self.assertEqual(fresh, [])

    def test_official_blog_is_excluded(self):
        api = FakeAPI(naver_blog=[nb('커밍아웃 스토리 신간', 'https://blog.naver.com/hantijae_publisher/9', '한티재', '20260925')])
        _, fresh = self.scan(api)
        self.assertEqual((fresh, Signal.objects.count()), ([], 0))

    def test_llm_failure_keeps_baseline_and_leaves_fresh_for_next_time(self):
        api = FakeAPI(naver_blog=[nb('커밍아웃 스토리 독후감', 'https://blog.naver.com/a/1', '한티재', '20260925'),
                                  nb('커밍아웃 스토리 독후감', 'https://blog.naver.com/a/0', '한티재', '20260101')])
        report, fresh = reviews.scan(TODAY, books=[self.book], cfg=CFG, get_json=api, sleep=no_sleep)
        with self.assertLogs('intake', level='WARNING'), self.assertRaises(RuntimeError):
            reviews.save_judged(FlakyLLM(fail_first=9), fresh, report)
        self.assertEqual(list(Signal.objects.values_list('url', flat=True)), ['https://blog.naver.com/a/0'])
        _, again = reviews.scan(TODAY, books=[self.book], cfg=CFG, get_json=api, sleep=no_sleep)
        self.assertEqual([p.url for _, p, _ in again], ['https://blog.naver.com/a/1'])

    def test_calls_are_spaced(self):
        sleeps = []
        self.scan(FakeAPI(), sleep=sleeps.append)
        self.assertEqual(sleeps, [reviews.SPACING] * (4 * 2 - 1))   # 출처 4곳 × 질의 2개, 첫 호출 앞에는 쉬지 않는다

    def test_failing_source_stops_after_three_in_a_row(self):
        books = [self.book,
                 make_book(title='책 2', published=date(2020, 1, 1), isbn='979-11-00003-02-0'),
                 make_book(title='책 3', published=date(2020, 1, 1), isbn='979-11-00003-03-0')]
        api = FakeAPI(raise_for={'daum_blog'})
        with self.assertLogs('intake', level='WARNING'):
            report, _ = self.scan(api, books=books)
        self.assertEqual(api.calls.count('daum_blog'), 3)
        self.assertEqual(report.failed, ['daum_blog'])
        self.assertEqual(api.calls.count('naver_blog'), 6)

    def test_book_not_marked_scanned_when_every_search_failed(self):
        api = FakeAPI(raise_for={'naver_blog', 'naver_cafe', 'daum_blog', 'daum_cafe'})
        with self.assertLogs('intake', level='WARNING'):
            report, _ = self.scan(api)
        self.assertEqual(report.failed, ['naver_blog', 'naver_cafe', 'daum_blog', 'daum_cafe'])
        self.assertFalse([k for k in WorkerState.get(reviews.SCANNED) or [] if k.startswith(f'{self.book.id}:')])

    def test_todays_books_takes_one_seventh_by_id(self):
        books = [make_book(title=f'책 {i}', published=date(2020, 1, 1), isbn=f'979-11-00001-{i:02d}-0', author=None)
                 for i in range(10)]
        hidden = make_book(title='안 나온 책', published=date(2020, 1, 1), isbn='979-11-00002-00-0', author=None,
                           is_published=False)
        picked = {b.id for b in reviews.todays_books(TODAY)}
        expected = {b.id for b in books + [self.book] if b.id % 7 == TODAY.toordinal() % 7}
        self.assertEqual(picked, expected)
        self.assertNotIn(hidden.id, picked)

    def test_cafe_baseline_waits_for_the_cafe_search_to_succeed(self):
        """카페 검색만 실패한 날엔 카페 기준선이 없다 → 카페가 처음 성공한 날의 날짜 없는 글은 새 글이 아니다."""
        with self.assertLogs('intake', level='WARNING'):
            self.scan(FakeAPI(naver_blog=[nb('커밍아웃 스토리 독후감', 'https://blog.naver.com/a/0', '한티재', '20260101')],
                              raise_for={'naver_cafe'}))
        llm = FakeLLM(REVIEW)
        report, fresh = self.scan(FakeAPI(naver_cafe=[nc('옛 모임 후기', 'https://cafe.naver.com/c/9', '&lt;커밍아웃 스토리&gt; 읽기')]), llm)
        self.assertEqual((fresh, llm.calls), ([], []))
        self.assertEqual(Signal.objects.get(url='https://cafe.naver.com/c/9').detail['verdict'], 'old')

    def test_save_old_records_a_baseline(self):
        post = Post('ig_tag', 'https://www.instagram.com/p/A/', '북클럽', '커밍아웃 스토리', date(2026, 1, 4))
        s = reviews.save_old(self.book, post, reviews.signal_key(self.book, post))
        self.assertEqual((s.kind, s.relevant, s.detail['verdict'], s.detail['source']), ('review', False, 'old', 'ig_tag'))


@override_settings(MARKETING=CFG)
class RunTest(TestCase):
    def setUp(self):
        self.book = make_book(title='커밍아웃 스토리', subtitle='성소수자와 그 부모들의 이야기', published=date(2018, 6, 11),
                              isbn='979-11-00000-01-1', author='성소수자부모모임')
        self.notes = []

    def deps(self, llm=None):
        return SimpleNamespace(llm=llm or FakeLLM({'items': []}), bot=SimpleNamespace(notify_admin=self.notes.append))

    def test_failure_streak_alerts_once_on_third_day(self):
        api = FakeAPI(raise_for={'naver_cafe'})
        with self.assertLogs('intake', level='WARNING'):
            for _ in range(4):
                reviews.run(self.deps(), TODAY, books=[self.book], get_json=api, sleep=no_sleep)
        self.assertEqual(len([n for n in self.notes if '네이버 카페' in n and '3일째' in n]), 1)
        reviews.run(self.deps(), TODAY, books=[self.book], get_json=FakeAPI(), sleep=no_sleep)
        self.assertEqual(WorkerState.get('review_fail_naver_cafe'), 0)

    def test_judge_failure_raises_after_tracking_failures(self):
        api = FakeAPI(naver_blog=[nb('커밍아웃 스토리 독후감', 'https://blog.naver.com/a/1', '한티재', '20260925')],
                      raise_for={'daum_cafe'})
        with self.assertLogs('intake', level='WARNING'), self.assertRaises(RuntimeError):
            reviews.run(self.deps(FlakyLLM(fail_first=9)), TODAY, books=[self.book], get_json=api, sleep=no_sleep)
        self.assertEqual(WorkerState.get('review_fail_daum_cafe'), 1)

    def test_returns_report_with_new_reviews(self):
        api = FakeAPI(naver_blog=[nb('커밍아웃 스토리 독후감', 'https://blog.naver.com/a/1', '한티재', '20260925')])
        report = reviews.run(self.deps(FakeLLM(REVIEW)), TODAY, books=[self.book], get_json=api, sleep=no_sleep)
        self.assertEqual([s.url for s in report.reviews], ['https://blog.naver.com/a/1'])


class CommandTest(TestCase):
    def setUp(self):
        self.book = make_book(title='커밍아웃 스토리', subtitle='', published=date(2018, 6, 11),
                              isbn='979-11-00000-01-1', author='성소수자부모모임')

    def fake_scan(self, today, books=None, **kw):
        Signal.objects.create(kind='review', key='review:x', book=self.book, title='기준선')
        post = Post('naver_blog', 'https://blog.naver.com/a/1', '커밍아웃 스토리 독후감', '한티재', date(2026, 9, 25))
        return reviews.Report(books=len(books or []), found=1, baseline=1), [(terms(self.book), post, 'review:y')]

    def test_dry_run_rolls_back_and_prints(self):
        out = StringIO()
        with mock.patch('marketing.reviews.scan', side_effect=self.fake_scan), \
                mock.patch('intake.deps.build_deps', return_value=SimpleNamespace(llm=FakeLLM(REVIEW))):
            call_command('marketing_scan_reviews', '--dry-run', '--book', str(self.book.id), stdout=out)
        text = out.getvalue()
        self.assertIn('책 1권, 새 글 1건(서평 1건), 기준선 1건, 실패한 출처 없음', text)
        self.assertIn('『커밍아웃 스토리』 [네이버 블로그] 커밍아웃 스토리 독후감 | 2026-09-25 | review 읽은 감상', text)
        self.assertIn('(dry-run: 기록하지 않았어요)', text)
        self.assertEqual(Signal.objects.count(), 0)

    def test_no_judge_does_not_touch_the_llm(self):
        out = StringIO()
        with mock.patch('marketing.reviews.scan', side_effect=self.fake_scan), \
                mock.patch('intake.deps.build_deps') as build, mock.patch('marketing.reviews.save_judged') as judged:
            call_command('marketing_scan_reviews', '--dry-run', '--no-judge', '--book', str(self.book.id), stdout=out)
        build.assert_not_called()
        judged.assert_not_called()
        self.assertIn('| 판별 안 함 |', out.getvalue())
