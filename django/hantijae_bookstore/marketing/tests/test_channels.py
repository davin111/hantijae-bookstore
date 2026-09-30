from datetime import date, datetime, timezone

from django.test import SimpleTestCase

from marketing import channels
from marketing.meta import ChannelPost

MON = date(2026, 10, 5)
AT = datetime(2026, 9, 29, 3, 0, tzinfo=timezone.utc)


def fb(text, r, c=0, s=0):
    return ChannelPost('facebook', AT, text, 'https://f/1', r, c, s)


def ig(text, r, c=0):
    return ChannelPost('instagram', AT, text, 'https://i/1', r, c)


class WeekLineTest(SimpleTestCase):
    def test_counts_and_top_post(self):
        seen = []
        got = {'facebook': [fb('굴삭기를 몰고 농사일을 도우면서도 통기타를 놓지 않는 가수', 12, 3, 2), fb('시 소개', 5)],
               'instagram': [ig('2쇄를 찍었습니다', 21, 1)]}
        line = channels.week_line(MON, fetch=lambda since, until: seen.append((since, until)) or got)
        self.assertEqual(line, '지난주 공식 채널: 페북 2건 반응 17·댓글 3·공유 2, 인스타 1건 좋아요 21·댓글 1. '
                               '반응이 가장 큰 글: 인스타 「2쇄를 찍었습니다」 22')
        since, until = seen[0]
        self.assertEqual((since.date().isoformat(), until.date().isoformat()), ('2026-09-28', '2026-10-05'))

    def test_long_text_is_cut(self):
        got = {'facebook': [fb('굴삭기를 몰고 농사일을 도우면서도 통기타를 놓지 않는 가수', 30)], 'instagram': []}
        line = channels.week_line(MON, fetch=lambda since, until: got)
        self.assertIn('「굴삭기를 몰고 농사일을 도우면서도 통기타를…」 30', line)
        self.assertIn('인스타 0건 좋아요 0·댓글 0', line)

    def test_line_says_when_a_channel_could_not_be_read(self):
        line = channels.week_line(MON, fetch=lambda since, until: {'facebook': [fb('글', 4)], 'instagram': None})
        self.assertIn('인스타는 읽지 못했어요', line)
        self.assertEqual(channels.week_line(MON, fetch=lambda since, until: {'facebook': None, 'instagram': None}), '')

    def test_no_posts_has_no_top_post(self):
        line = channels.week_line(MON, fetch=lambda since, until: {'facebook': [], 'instagram': []})
        self.assertEqual(line, '지난주 공식 채널: 페북 0건 반응 0·댓글 0·공유 0, 인스타 0건 좋아요 0·댓글 0')
