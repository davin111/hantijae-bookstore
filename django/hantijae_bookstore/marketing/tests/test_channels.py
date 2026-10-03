from datetime import date, datetime, timezone

from django.test import TestCase

from marketing import channels
from marketing.meta import ChannelPost
from marketing.tests.fakes import make_ad, make_book
from marketing.timeutil import KST

MON = date(2026, 10, 5)
AT = datetime(2026, 9, 29, 3, 0, tzinfo=timezone.utc)


def fb(text, r, c=0, s=0):
    return ChannelPost('facebook', AT, text, 'https://f/1', r, c, s)


def ig(text, r, c=0):
    return ChannelPost('instagram', AT, text, 'https://i/1', r, c)


class WeekLineTest(TestCase):
    def test_counts_and_top_post(self):
        seen = []
        got = {'facebook': [fb('굴삭기를 몰고 농사일을 도우면서도 통기타를 놓지 않는 가수', 12, 3, 2), fb('시 소개', 5)],
               'instagram': [ig('2쇄를 찍었습니다', 21, 1)]}
        line = channels.week_line(MON, fetch=lambda since, until: seen.append((since, until)) or got)
        self.assertEqual(line, '지난주 공식 채널: 페북 2건 반응 17·댓글 3·공유 2, 인스타 1건 좋아요 21·댓글 1. '
                               '반응이 가장 큰 글: 인스타 「2쇄를 찍었습니다」(반응 합계 22)')
        since, until = seen[0]
        self.assertEqual((since, until), (datetime(2026, 9, 28, tzinfo=KST), datetime(2026, 10, 5, tzinfo=KST)))

    def test_long_text_is_cut(self):
        got = {'facebook': [fb('굴삭기를 몰고 농사일을 도우면서도 통기타를 놓지 않는 가수', 30)], 'instagram': []}
        line = channels.week_line(MON, fetch=lambda since, until: got)
        self.assertIn('「굴삭기를 몰고 농사일을 도우면서도 통기타를…」(반응 합계 30)', line)
        self.assertIn('인스타 글 없음', line)

    def test_line_says_when_a_channel_could_not_be_read(self):
        line = channels.week_line(MON, fetch=lambda since, until: {'facebook': [fb('글', 4)], 'instagram': None})
        self.assertIn('인스타는 읽지 못했어요', line)
        self.assertEqual(channels.week_line(MON, fetch=lambda since, until: {'facebook': None, 'instagram': None}), '')

    def test_no_posts_has_no_top_post(self):
        line = channels.week_line(MON, fetch=lambda since, until: {'facebook': [], 'instagram': []})
        self.assertEqual(line, '지난주 공식 채널: 페북 글 없음, 인스타 글 없음')


def fbid(text, r, post_id):
    return ChannelPost('facebook', AT, text, 'https://f/1', r, 0, 0, id=post_id)


class AdMarkTest(TestCase):
    def test_ad_posts_are_left_out_of_the_top_post_and_the_ad_is_named(self):
        make_ad(post_id='111_1', book=make_book(), days=[date(2026, 9, 28), date(2026, 9, 29)], reach=6000)
        got = {'facebook': [fbid('광고한 글', 400, '111_1'), fbid('평소 글', 12, '111_2')], 'instagram': []}
        line = channels.week_line(MON, fetch=lambda since, until: got)
        self.assertIn('페북 2건 반응 412', line)   # 합계는 그대로
        self.assertIn('광고하지 않은 글 중 반응이 가장 큰 글: 페북 「평소 글」(반응 합계 12)', line)
        self.assertTrue(line.endswith('. 지난주 광고: 『나는 산속으로 더 깊이 들어간다』 글 2일 · 10,000원 · '
                                      '지금까지 6,000명에게 보였어요'))

    def test_no_ads_keeps_the_old_wording(self):
        got = {'facebook': [fbid('평소 글', 12, '111_2')], 'instagram': []}
        self.assertIn('. 반응이 가장 큰 글: 페북', channels.week_line(MON, fetch=lambda since, until: got))

    def test_both_channels_unreadable_still_tell_the_ad(self):
        make_ad(days=[date(2026, 9, 30)])
        line = channels.week_line(MON, fetch=lambda since, until: {'facebook': None, 'instagram': None})
        self.assertTrue(line.startswith('지난주 광고: '))
