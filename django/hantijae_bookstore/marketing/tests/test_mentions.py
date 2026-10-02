from datetime import date
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from marketing import mentions, reviews
from marketing.models import Signal
from marketing.tests.fakes import FakeLLM, make_book

TODAY = date(2026, 9, 30)
CFG = {'GOOGLE_ALERTS_FEEDS': '["https://alerts.example/feed/SECRETFEED"]', 'YOUTUBE_API_KEY': 'kk'}
REVIEW = {'items': [{'id': 0, 'verdict': 'review', 'reason': '책 이야기'}]}
TWO_REVIEW = {'items': [{'id': 0, 'verdict': 'review', 'reason': '책 이야기'}, {'id': 1, 'verdict': 'review', 'reason': '책 이야기'}]}


def feed(*entries):
    body = ''.join(f'<entry><title>{t}</title><link href="{u}"/><published>{d}T01:00:00Z</published>'
                   f'<content>{c}</content></entry>' for t, u, d, c in entries)
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'.encode()


def video(vid, title, day, desc='', channel='개인 채널 이름'):
    return {'id': {'videoId': vid}, 'snippet': {'publishedAt': f'{day}T10:00:00Z', 'title': title,
                                                 'description': desc, 'channelTitle': channel}}


def no_sleep(_):
    pass


class MentionsTest(TestCase):
    def setUp(self):
        self.mu = make_book(title='무궁화호를 위하여', subtitle='', published=date(2026, 3, 16), isbn='979-11-00000-16-1',
                            author='하승우')
        self.notes = []

    def run_scan(self, feed_bytes=b'<feed xmlns="http://www.w3.org/2005/Atom"/>', videos=(), llm=None, yt_error=None,
                 feed_error=False, books=None):
        calls = []

        def get_bytes(url):
            calls.append('feed')
            if feed_error:
                raise RuntimeError(f'500 for url {url}')
            return feed_bytes

        def get_json(url, headers=None):
            calls.append('youtube')
            if yt_error:
                raise RuntimeError('403 quotaExceeded')
            return {'items': list(videos)}

        deps = SimpleNamespace(llm=llm or FakeLLM(REVIEW))
        report = mentions.run(deps, TODAY, self.notes.append, books=[self.mu] if books is None else books, cfg=CFG,
                              get_bytes=get_bytes, get_json=get_json, sleep=no_sleep)
        return report, calls

    def test_alert_about_a_book_is_judged(self):
        report, _ = self.run_scan(feed(('「무궁화호를 위하여」 하승우 인터뷰', 'https://news.example.com/a/1', '2026-09-27',
                                        '도서출판 한티재')))
        s = Signal.objects.get()
        self.assertEqual((s.book, s.detail['source'], s.relevant, s.url), (self.mu, 'web', True, 'https://news.example.com/a/1'))
        self.assertEqual([x.pk for x in report.reviews], [s.pk])

    def test_own_site_and_blog_are_skipped(self):
        self.run_scan(feed(('무궁화호를 위하여 - 도서출판 한티재', 'https://hantijae-bookstore.com/book=5', '2026-09-27', '한티재'),
                           ('무궁화호를 위하여 신간', 'https://blog.naver.com/hantijae_publisher/1', '2026-09-27', '한티재')))
        self.assertEqual(Signal.objects.count(), 0)

    def test_youtube_video_about_the_book(self):
        llm = FakeLLM(REVIEW)
        _, calls = self.run_scan(videos=[video('V1', '[북토크] 무궁화호를 위하여 하승우', '2026-09-25')], llm=llm)
        s = Signal.objects.get()
        self.assertEqual((s.detail['source'], s.url), ('youtube', 'https://www.youtube.com/watch?v=V1'))
        self.assertEqual(calls.count('youtube'), 1)   # 책마다 한 번(질의 하나)

    def test_channel_name_is_not_stored(self):
        self.run_scan(videos=[video('V1', '[북토크] 무궁화호를 위하여 하승우', '2026-09-25', channel='홍길동TV')])
        s = Signal.objects.get()
        self.assertNotIn('홍길동TV', str(s.detail) + s.title)
        self.assertEqual(s.detail['where'], '')

    def test_seen_mentions_are_not_judged_again(self):
        v = [video('V1', '[북토크] 무궁화호를 위하여 하승우', '2026-09-25')]
        self.run_scan(videos=v)
        llm = FakeLLM(REVIEW)
        self.run_scan(videos=v, llm=llm)
        self.assertEqual((Signal.objects.count(), llm.calls), (1, []))

    def test_old_posts_are_baseline(self):
        llm = FakeLLM(REVIEW)
        self.run_scan(feed(('「무궁화호를 위하여」 하승우', 'https://news.example.com/old', '2026-08-01', '한티재')), llm=llm)
        self.assertEqual((Signal.objects.get().detail['verdict'], llm.calls), ('old', []))

    def test_short_title_guard_is_not_defeated_by_hantijae_in_every_alert(self):
        """알리미 질의가 '도서출판 한티재'라 모든 글에 '한티재'가 있다 — 그걸로 짧은 제목 보호를 뚫으면 안 된다(F3).
        (brief 예시 문구 '도서출판 한티재 …'·'… 출판사 소식'은 '도서'·'출판'이 BOOK_WORDS라 다른 경로로도 걸려
        그 문구로는 이 가드만 따로 보일 수 없다 — '한티재'만 단서인 문구로 바꿨다.)"""
        make_book(title='기후정의', subtitle='', published=date(2020, 1, 1), isbn='979-11-00003-00-0', author='다른사람')
        self.run_scan(feed(('한티재와 함께 기후정의행진에 걸어요', 'https://news.example.com/b/1', '2026-09-27',
                            '기후위기 대응 소식')))
        self.assertEqual(Signal.objects.count(), 0)

    def test_one_alert_naming_two_books_makes_a_signal_for_each(self):
        other = make_book(title='커밍아웃 스토리', subtitle='', published=date(2018, 6, 11),
                          isbn='979-11-00000-21-1', author='성소수자부모모임')
        self.run_scan(feed(('「무궁화호를 위하여」 하승우와 「커밍아웃 스토리」 성소수자부모모임을 함께 다룬 기사',
                            'https://news.example.com/c/1', '2026-09-27', '도서출판 한티재')), llm=FakeLLM(TWO_REVIEW))
        signals = list(Signal.objects.all())
        self.assertEqual(len(signals), 2)
        self.assertEqual({s.book_id for s in signals}, {self.mu.id, other.id})
        self.assertEqual({s.url for s in signals}, {'https://news.example.com/c/1'})

    def test_youtube_give_up_does_not_stop_alerts(self):
        """유튜브가 사흘째가 아니라 그날 바로 멈춰도(한 바퀴 안 연속 실패) 알리미 수집은 그대로 간다."""
        books = [self.mu] + [make_book(title=f'책 이름 {i}', subtitle='', published=date(2020, 1, 1),
                                       isbn=f'979-11-00004-{i:02d}-0', author=None) for i in range(4)]
        with self.assertLogs('intake', level='WARNING'):
            report, _ = self.run_scan(feed(('「무궁화호를 위하여」 하승우 인터뷰', 'https://news.example.com/d/1', '2026-09-27',
                                            '도서출판 한티재')), yt_error=True, books=books)
        self.assertIn('youtube', report.failed)
        s = Signal.objects.get(url='https://news.example.com/d/1')
        self.assertEqual(s.detail['source'], 'web')

    def test_youtube_gives_up_after_three_failures(self):
        """한 바퀴(YOUTUBE_GIVE_UP) 안의 give-up과, 사흘 연속 실패해야 뜨는 알림(FAIL_ALERT_DAYS)은 다른 셈이다(F2)."""
        books = [self.mu] + [make_book(title=f'책 이름 {i}', subtitle='', published=date(2020, 1, 1),
                                       isbn=f'979-11-00001-{i:02d}-0', author=None) for i in range(4)]
        for day in range(reviews.FAIL_ALERT_DAYS):
            with self.assertLogs('intake', level='WARNING'):
                report, calls = self.run_scan(yt_error=True, books=books)
            self.assertEqual(calls.count('youtube'), mentions.YOUTUBE_GIVE_UP)
            self.assertIn('youtube', report.failed)
            expect_note = day == reviews.FAIL_ALERT_DAYS - 1
            self.assertEqual(len([n for n in self.notes if '유튜브' in n]), 1 if expect_note else 0)

    def test_youtube_failure_streak_resets_after_a_success(self):
        books = [self.mu] + [make_book(title=f'책 이름 {i}', subtitle='', published=date(2020, 1, 1),
                                       isbn=f'979-11-00002-{i:02d}-0', author=None) for i in range(4)]
        with self.assertLogs('intake', level='WARNING'):
            self.run_scan(yt_error=True, books=books)
        with self.assertLogs('intake', level='WARNING'):
            self.run_scan(yt_error=True, books=books)
        self.run_scan(books=books)   # 중간에 성공 → 연속 실패가 끊긴다
        with self.assertLogs('intake', level='WARNING'):
            self.run_scan(yt_error=True, books=books)
        with self.assertLogs('intake', level='WARNING'):
            self.run_scan(yt_error=True, books=books)
        self.assertEqual(len([n for n in self.notes if '유튜브' in n]), 0)

    def test_feed_failure_never_logs_the_feed_url(self):
        for day in range(reviews.FAIL_ALERT_DAYS):
            with self.assertLogs('intake', level='WARNING') as cm:
                report, _ = self.run_scan(feed_error=True)
            self.assertNotIn('SECRETFEED', '\n'.join(cm.output))
            self.assertIn('web', report.failed)
            expect_note = day == reviews.FAIL_ALERT_DAYS - 1
            self.assertEqual(len([n for n in self.notes if '웹 언급' in n]), 1 if expect_note else 0)
        self.assertNotIn('SECRETFEED', ' '.join(self.notes))

    def test_missing_keys_do_nothing(self):
        deps = SimpleNamespace(llm=FakeLLM(REVIEW))
        report = mentions.run(deps, TODAY, self.notes.append, books=[self.mu], cfg={},
                              get_bytes=lambda url: 1 / 0, get_json=lambda url, headers=None: 1 / 0, sleep=no_sleep)
        self.assertEqual((report.found, report.failed, self.notes), (0, [], []))


class CommandTest(TestCase):
    def test_dry_run_rolls_back_and_prints(self):
        from marketing import reviews
        from marketing.review_filter import terms
        from marketing.review_search import Post
        book = make_book(title='무궁화호를 위하여', subtitle='', published=date(2026, 3, 16), isbn='979-11-00000-16-1',
                         author='하승우')

        def fake_scan(today, books=None, **kw):
            Signal.objects.create(kind='review', key='review:x', book=book, title='기준선')
            post = Post('youtube', 'https://www.youtube.com/watch?v=V1', '[북토크] 무궁화호를 위하여', '하승우', date(2026, 9, 25))
            return reviews.Report(books=1, found=1, baseline=1), [(terms(book), post, 'review:y')]

        out = StringIO()
        with mock.patch('marketing.mentions.scan', side_effect=fake_scan), \
                mock.patch('intake.deps.build_deps', return_value=SimpleNamespace(llm=FakeLLM(REVIEW))):
            call_command('marketing_scan_web', '--dry-run', stdout=out)
        text = out.getvalue()
        self.assertIn('새 글 1건(서평 1건), 기준선 1건, 읽지 못한 곳 없음', text)
        self.assertIn('『무궁화호를 위하여』 [유튜브] [북토크] 무궁화호를 위하여 | 2026-09-25 | review 책 이야기', text)
        self.assertIn('(dry-run: 기록하지 않았어요)', text)
        self.assertEqual(Signal.objects.count(), 0)
