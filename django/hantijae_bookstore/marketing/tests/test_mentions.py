from datetime import date
from types import SimpleNamespace

from django.test import TestCase

from marketing import mentions
from marketing.models import Signal
from marketing.tests.fakes import FakeLLM, make_book

TODAY = date(2026, 9, 30)
CFG = {'GOOGLE_ALERTS_FEEDS': '["https://alerts.example/feed/SECRETFEED"]', 'YOUTUBE_API_KEY': 'kk'}
REVIEW = {'items': [{'id': 0, 'verdict': 'review', 'reason': '책 이야기'}]}


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

    def test_youtube_gives_up_after_three_failures(self):
        books = [self.mu] + [make_book(title=f'책 이름 {i}', subtitle='', published=date(2020, 1, 1),
                                       isbn=f'979-11-00001-{i:02d}-0', author=None) for i in range(4)]
        with self.assertLogs('intake', level='WARNING'):
            report, calls = self.run_scan(yt_error=True, books=books)
        self.assertEqual(calls.count('youtube'), mentions.YOUTUBE_GIVE_UP)
        self.assertIn('youtube', report.failed)
        self.assertEqual(len([n for n in self.notes if '유튜브' in n]), 1)

    def test_feed_failure_never_logs_the_feed_url(self):
        with self.assertLogs('intake', level='WARNING') as cm:
            report, _ = self.run_scan(feed_error=True)
        self.assertNotIn('SECRETFEED', '\n'.join(cm.output))
        self.assertIn('web', report.failed)
        self.assertEqual(len([n for n in self.notes if '알리미' in n]), 1)
        self.assertNotIn('SECRETFEED', ' '.join(self.notes))

    def test_missing_keys_do_nothing(self):
        deps = SimpleNamespace(llm=FakeLLM(REVIEW))
        report = mentions.run(deps, TODAY, self.notes.append, books=[self.mu], cfg={},
                              get_bytes=lambda url: 1 / 0, get_json=lambda url, headers=None: 1 / 0, sleep=no_sleep)
        self.assertEqual((report.found, report.failed, self.notes), (0, [], []))
