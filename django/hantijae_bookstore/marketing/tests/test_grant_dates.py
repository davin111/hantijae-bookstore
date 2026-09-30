from datetime import date

from django.test import SimpleTestCase

from marketing.grant_dates import verify

# 실제 공고문 PDF에서 뽑은 조각(pypdf, 2026-09-30). 한글 글꼴 탓에 요일·'시' 위치가 흐트러져 있다
THIRD_EBOOK = '신청 기간 금 시 2026. 10. 2.( ) 10 ~ 월 시까지10. 12.( ) 16 일간 [11 ] 신청 방법 전자책바로센터'
AUDIOBOOK = '접수 기간 목 시부터 목 시까지2026. 5. 21.( ) 10 ~ 5. 28.( ) 16 일간[8 ] 제출 서류'
MARKETING = '접수기간 공고 및 접수기간 화 화 시 - : 3.31.( ) ~ 4.14.( ) 17 선정 심사위원회 개최 월 하순 예정'
SEJONG = ('신청대상 개월 기간 중 국내에서 초판 발행된 교양도서2025. 5. 1. ~ 2026. 2. 28.(10 ) 바코드 '
          '온라인 신청 세종도서 온라인시스템 : 기간 · : 월 금2026. 3. 30.( ) 09:00 4. 10.( ) 18:00∼ 기간엄수( )')
LIT_TYPO = '온라인 신청 세종도서 온라인시스템 : 기간 · : 월 금2025. 3. 30.( ) 09:00 4. 10.( ) 18:00∼ 기간엄수( )'


def raw(until, start='', time=''):
    return {'apply_from': start, 'apply_until': until, 'until_time': time}


class VerifyTest(SimpleTestCase):
    def test_real_notice_fragments(self):
        cases = [
            (THIRD_EBOOK, date(2026, 9, 29), raw('2026-10-12', '2026-10-02', '16:00'), date(2026, 10, 2), date(2026, 10, 12), '16:00'),
            (AUDIOBOOK, date(2026, 5, 14), raw('2026-05-28', '2026-05-21', '16'), date(2026, 5, 21), date(2026, 5, 28), '16:00'),
            (MARKETING, date(2026, 3, 31), raw('2026-04-14', '2026-03-31', '17:00'), date(2026, 3, 31), date(2026, 4, 14), '17:00'),
            (SEJONG, date(2026, 3, 23), raw('2026-04-10', '2026-03-30', '18:00'), date(2026, 3, 30), date(2026, 4, 10), '18:00'),
        ]
        for text, posted, answer, start, until, clock in cases:
            with self.subTest(until=until):
                self.assertEqual(verify(answer, text, posted),
                                 {'apply_from': start, 'apply_until': until, 'until_time': clock, 'date_checked': True})

    def test_year_comes_from_posting_date_not_the_notice(self):
        got = verify(raw('2025-04-10', '2025-03-30', '18:00'), LIT_TYPO, date(2026, 3, 23))
        self.assertEqual((got['apply_from'], got['apply_until']), (date(2026, 3, 30), date(2026, 4, 10)))

    def test_deadline_in_next_year(self):
        got = verify(raw('2027-01-08'), '접수 마감 2027. 1. 8.(금) 18:00', date(2026, 12, 20))
        self.assertEqual(got['apply_until'], date(2027, 1, 8))

    def test_date_not_in_text_is_dropped(self):
        self.assertEqual(verify(raw('2026-10-20', '2026-10-02', '16:00'), THIRD_EBOOK, date(2026, 9, 29)),
                         {'apply_from': date(2026, 10, 2), 'apply_until': None, 'until_time': '', 'date_checked': False})

    def test_publication_window_date_is_rejected(self):
        # 세종도서 공고의 발행 기간 끝(2026-02-28)은 게시일(3/23)보다 앞 → 다음 해로 풀리면 120일을 넘는다
        self.assertIsNone(verify(raw('2026-02-28'), SEJONG, date(2026, 3, 23))['apply_until'])

    def test_more_than_120_days_after_posting_is_rejected(self):
        self.assertIsNone(verify(raw('2026-10-12'), THIRD_EBOOK, date(2026, 5, 1))['apply_until'])

    def test_program_period_end_is_rejected(self):
        # 사업 기간 끝(게시일 뒤)을 마감으로 잘못 뽑으면 실제 마감 뒤에 알림이 간다(최종 검토 지적)
        text = '신청 기간 2026. 10. 2. ~ 10. 12. 16시 / 사업 기간 협약일 ~ 2026. 11. 30.'
        got = verify(raw('2026-11-30', '2026-10-02'), text, date(2026, 9, 29))
        self.assertEqual((got['apply_until'], got['date_checked']), (None, False))

    def test_long_window_is_rejected_even_without_start(self):
        text = '사업 기간 ~ 2026. 12. 20. 까지'
        self.assertIsNone(verify(raw('2026-12-20'), text, date(2026, 10, 1))['apply_until'])

    def test_bad_values(self):
        for value in ('', 'garbage', '2026-13-01', '2026-02-30', None):
            with self.subTest(value=value):
                self.assertFalse(verify(raw(value), THIRD_EBOOK, date(2026, 9, 29))['date_checked'])

    def test_time_must_follow_the_deadline_in_text(self):
        self.assertEqual(verify(raw('2026-10-12', time='09:00'), THIRD_EBOOK, date(2026, 9, 29))['until_time'], '')
        self.assertEqual(verify(raw('2026-10-12', time='25:00'), THIRD_EBOOK, date(2026, 9, 29))['until_time'], '')

    def test_start_after_deadline_is_dropped(self):
        got = verify(raw('2026-10-02', '2026-10-12'), THIRD_EBOOK, date(2026, 9, 29))
        self.assertEqual((got['apply_from'], got['apply_until']), (None, date(2026, 10, 2)))
