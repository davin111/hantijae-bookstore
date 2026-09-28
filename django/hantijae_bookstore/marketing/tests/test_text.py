from datetime import date, datetime, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase

from marketing import prompts
from marketing.text import clip, fix_title_marks, foreign_numbers, title_key, unverified_quotes, won_display
from marketing.timeutil import in_quiet_hours, kst_today, week_start


class TimeTest(SimpleTestCase):
    def test_kst_today_crosses_utc_midnight(self):
        self.assertEqual(kst_today(datetime(2026, 9, 27, 22, 0, tzinfo=timezone.utc)), date(2026, 9, 28))

    def test_quiet_hours_are_21_to_08_kst(self):
        self.assertTrue(in_quiet_hours(datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)))   # 21:00 KST
        self.assertTrue(in_quiet_hours(datetime(2026, 9, 27, 22, 59, tzinfo=timezone.utc)))  # 07:59 KST
        self.assertFalse(in_quiet_hours(datetime(2026, 9, 27, 23, 0, tzinfo=timezone.utc)))  # 08:00 KST

    def test_week_start_is_monday(self):
        self.assertEqual(week_start(date(2026, 10, 4)), date(2026, 9, 28))
        self.assertEqual(week_start(date(2026, 9, 28)), date(2026, 9, 28))


class TextTest(SimpleTestCase):
    def test_fix_title_marks_moves_subtitle_out(self):
        self.assertEqual(fix_title_marks('『시월, 곡비의 노래 ― 10월문학회 시선집』, 80주년'),
                         '『시월, 곡비의 노래』 ― 10월문학회 시선집, 80주년')
        self.assertEqual(fix_title_marks('『내란 앞에서』 ― 일지'), '『내란 앞에서』 ― 일지')

    def test_unverified_quotes_ignores_whitespace_differences(self):
        source = '몸을 통과한 흙과 풀의 이야기가 시가 될 때 나는 큰 위로를 받는다.'
        text = '"몸을 통과한 흙과 풀의 이야기가  시가 될 때" 그리고 "지어낸 문장이 여기 들어 있다"'
        self.assertEqual(unverified_quotes(text, source), ['지어낸 문장이 여기 들어 있다'])
        self.assertEqual(unverified_quotes('"지어낸 문장이 여기 들어 있다"', source), ['지어낸 문장이 여기 들어 있다'])

    def test_foreign_numbers_checks_three_digit_numbers_only(self):
        allowed = ['376권 펀딩, 6,768,000원', '2026-10-11']
        self.assertEqual(foreign_numbers('10월 11일 마감, 376권, 1부와 2부', allowed), [])
        self.assertEqual(foreign_numbers('벌써 500권이 모였어요 (6,768,000원)', allowed), ['500'])

    def test_clip_counts_utf16(self):
        self.assertEqual(clip('가나다', 10), '가나다')
        self.assertEqual(clip('가' * 20, 5), '가가가가…')

    def test_title_key_ignores_spaces_and_marks(self):
        self.assertEqual(title_key('『1.5 :  그레타 툰베리와 함께』'), title_key('1.5 : 그레타 툰베리와 함께'))

    def test_won_display(self):
        self.assertEqual(won_display(6768000), '677만 원')
        self.assertEqual(won_display(18480000), '1,848만 원')


class PromptTest(SimpleTestCase):
    def test_writing_prompts_start_with_voice(self):
        for p in (prompts.KIT_SYSTEM, prompts.BRIEFING_SYSTEM, prompts.REWRITE_SYSTEM):
            self.assertTrue(p.startswith(prompts.VOICE))
            self.assertIn('웹 검색', p)

    def test_build_kit_user_mentions_blog_status_and_hooks(self):
        book = SimpleNamespace(title='책', subtitle='', published_date=date(2026, 8, 21), page_count=132,
                               full_price=12000, description='소개', short_description='')
        text = prompts.build_kit_user(book, '최정 지음', date(2026, 9, 28), True, ['11월 1일 가을철 산불조심기간 시작'])
        self.assertIn('블로그 글: 이미 있음', text)
        self.assertIn('산불조심기간', text)

    def test_build_briefing_user_uses_candidate_prompts(self):
        c = SimpleNamespace(as_prompt=lambda: {'id': 'hook:1:2026-10-11'})
        self.assertIn('hook:1:2026-10-11', prompts.build_briefing_user([c], date(2026, 9, 28)))
