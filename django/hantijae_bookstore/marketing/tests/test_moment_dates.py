from datetime import date

from django.test import SimpleTestCase

from marketing.moment_dates import candidate_dates, date_supported

WED = date(2026, 9, 30)  # 수요일


class CandidateDatesTest(SimpleTestCase):
    def test_explicit_forms(self):
        for text in ('2026.10.17 저녁', '2026년 10월 17일(토)', '10월 17일', '10월17일', '10/17(토) 7시', '(토) 10.17',
                     '10-17 오후'):
            with self.subTest(text=text):
                self.assertIn(date(2026, 10, 17), candidate_dates(text, WED))

    def test_month_day_without_year_picks_nearest(self):
        self.assertIn(date(2027, 1, 10), candidate_dates('1/10에 북토크', date(2026, 12, 20)))
        self.assertIn(date(2026, 9, 18), candidate_dates('9/18에 시작했어요', WED))

    def test_day_only_this_or_next_month(self):
        days = candidate_dates('17일 저녁', WED)
        self.assertTrue({date(2026, 9, 17), date(2026, 10, 17)} <= days)
        self.assertIn(date(2026, 10, 3), candidate_dates('3일에 입고돼요', WED))

    def test_relative_words(self):
        self.assertTrue({WED, date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)}
                        <= candidate_dates('오늘 말고 내일, 모레, 글피', WED))

    def test_weekdays(self):
        self.assertIn(date(2026, 10, 2), candidate_dates('이번 주 금요일', WED))
        self.assertIn(date(2026, 10, 9), candidate_dates('다음 주 금요일에', WED))
        self.assertIn(date(2026, 10, 9), candidate_dates('담주 금요일', WED))
        self.assertIn(date(2026, 10, 16), candidate_dates('다다음 주 금요일', WED))
        self.assertNotIn(date(2026, 10, 9), candidate_dates('다다음 주 금요일', WED))
        bare = candidate_dates('금요일에 강연', WED)
        self.assertIn(date(2026, 10, 2), bare)
        self.assertIn(date(2026, 9, 28), candidate_dates('월요일에 했어요', WED))  # 이번 주 지난 요일
        self.assertIn(WED, candidate_dates('수요일 저녁', WED))  # 당일

    def test_weekend(self):
        self.assertTrue({date(2026, 10, 3), date(2026, 10, 4)} <= candidate_dates('주말에 북페어', WED))

    def test_numbers_that_are_not_dates(self):
        self.assertEqual(candidate_dates('2026년 신간, 264쪽, 22,000원, 260권', WED), set())
        self.assertEqual(candidate_dates('ISBN 979-11-92455-87-7', WED), set())


class SupportedTest(SimpleTestCase):
    def test_any_evidence_can_support(self):
        ev = [('펀딩 시작해요', date(2026, 9, 15)), ('금요일에 오픈', date(2026, 9, 16))]
        self.assertTrue(date_supported(date(2026, 9, 18), ev))
        self.assertFalse(date_supported(date(2026, 9, 19), ev))
        self.assertFalse(date_supported(date(2026, 9, 18), []))


class MentionTest(SimpleTestCase):
    def test_explicit_mentions(self):
        from marketing.moment_dates import explicit_mentions
        self.assertEqual(explicit_mentions('10월 17일 저자 강연', WED), [{date(2026, 10, 17)}])
        self.assertEqual(explicit_mentions('2026-10-02에 강연', WED), [{date(2026, 10, 2)}])
        self.assertEqual(explicit_mentions('17일 저녁 7시, 80주년', WED), [{date(2026, 9, 17), date(2026, 10, 17)}])
        self.assertEqual(explicit_mentions('저녁 7시 강연, 264쪽', WED), [])

    def test_unsupported_mentions(self):
        from marketing.moment_dates import unsupported_mentions
        ev = [('금요일에 강연 잡혔어요', date(2026, 9, 29))]
        self.assertEqual(unsupported_mentions('10월 2일 저자 강연', ev), [])
        self.assertEqual(unsupported_mentions('10월 17일 저자 강연', ev), [{date(2026, 10, 17)}])
        self.assertEqual(unsupported_mentions('2026-10-02 금요일에 강연', ev), [])


class SentDayTest(SimpleTestCase):
    def test_the_day_the_evidence_was_sent_is_allowed_in_text(self):
        from marketing.moment_dates import unsupported_mentions
        ev = [('AI 오디오북 제작 지원 사업에 선정됐어요', date(2026, 9, 28))]
        self.assertEqual(unsupported_mentions('9월 28일 방에 선정 소식을 알렸다', ev), [])
        self.assertEqual(unsupported_mentions('10월 5일 발표', ev), [{date(2026, 10, 5)}])
