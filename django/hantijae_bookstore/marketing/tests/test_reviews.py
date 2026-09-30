import json
from datetime import date

from django.test import TestCase

from marketing import reviews
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
