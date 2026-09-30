from datetime import date

from django.test import TestCase

from intake.models import WorkerState
from marketing import grants
from marketing.grant_sources import GRANT_LIST
from marketing.models import GrantCall
from marketing.tests.fakes import FakeLLM, tiny_pdf
from marketing.tests.test_grant_sources import row, view

TODAY = date(2026, 9, 30)
VIEW_2167 = 'https://www.kpipa.or.kr/p/g1_2/2167'
LIST = ('<ul>' + row('2167', '2026년 제3차 전자책 제작 지원 사업 공고', '26.09.29.')
        + row('2165', '2026년 웹소설 IP 2차 저작화 지원 사업 추가 모집 공고', '26.09.28.')
        + row('2134', '2026년 제6차 수출용 홍보자료(샘플) 지원 사업 공고', '26.08.03.') + '</ul>')
BODY = ('2026년 제3차 전자책 제작 지원 사업 공고 안내드립니다.<br />신청 기간 2026. 10. 2.(금) 10시 ~ 10. 12.(월) 16시'
        '<br />출판사당 최대 10종')
VERDICT = {'relevant': True, 'reason': '종이책이 있는 책이면 신청할 수 있어요',
           'support': '전자책 제작비 지원(출판사당 10종까지)', 'prep': '출판유통통합전산망 가입, 종이책 정보 등록',
           'apply_from': '2026-10-02', 'apply_until': '2026-10-12', 'until_time': '16:00'}


def pages(**extra):
    p = {GRANT_LIST: LIST, VIEW_2167: view('2026년 제3차 전자책 제작 지원 사업 공고', BODY)}
    p.update(extra)
    return p


def no_sleep(_):
    pass


def no_bytes(url):
    raise AssertionError(f'첨부를 받으면 안 돼요: {url}')


class ScanTest(TestCase):
    def scan(self, llm, p=None, today=TODAY, get_bytes=no_bytes):
        return grants.scan(llm, today, get_text=(p or pages()).__getitem__, get_bytes=get_bytes, sleep=no_sleep)

    def test_mode_defaults_off(self):
        self.assertEqual(grants.mode(), 'off')
        WorkerState.put('grant_mode', 'live')
        self.assertEqual(grants.mode(), 'live')

    def test_first_run_records_all_and_judges_only_fresh_unexcluded(self):
        llm = FakeLLM(VERDICT)
        report = self.scan(llm)
        self.assertEqual(dict(GrantCall.objects.values_list('key', 'state')),
                         {'kpipa:2167': GrantCall.READY, 'kpipa:2165': GrantCall.IGNORED, 'kpipa:2134': GrantCall.OLD})
        self.assertEqual(len(llm.calls), 1)
        call = GrantCall.objects.get(key='kpipa:2167')
        self.assertEqual(call.apply_until, date(2026, 10, 12))
        self.assertEqual({k: call.verdict[k] for k in ('apply_from', 'until_time', 'date_checked', 'support')},
                         {'apply_from': '2026-10-02', 'until_time': '16:00', 'date_checked': True,
                          'support': '전자책 제작비 지원(출판사당 10종까지)'})
        self.assertEqual((report.new, [c.key for c in report.ready]), (3, ['kpipa:2167']))
        self.assertIn('· 2026년 웹소설 IP 2차 저작화 지원 사업 추가 모집 공고 — 제목으로 뺌', grants.digest(report))

    def test_second_run_does_not_rejudge(self):
        llm = FakeLLM(VERDICT)
        self.scan(llm)
        report = self.scan(llm)
        self.assertEqual((len(llm.calls), report.new, grants.digest(report)), (1, 0, ''))

    def test_not_relevant_goes_to_admin_digest(self):
        report = self.scan(FakeLLM({**VERDICT, 'relevant': False, 'reason': '해외 도서전 참가사 모집이라 해당 없어요'}))
        self.assertEqual(GrantCall.objects.get(key='kpipa:2167').state, GrantCall.SKIPPED_LLM)
        self.assertIn('— 해외 도서전 참가사 모집이라 해당 없어요', grants.digest(report))

    def test_relevant_as_string_is_read(self):
        self.scan(FakeLLM({**VERDICT, 'relevant': 'true'}))
        self.assertEqual(GrantCall.objects.get(key='kpipa:2167').state, GrantCall.READY)

    def test_unverified_deadline_is_dropped_but_call_is_still_ready(self):
        self.scan(FakeLLM({**VERDICT, 'apply_until': '2026-10-20'}))
        call = GrantCall.objects.get(key='kpipa:2167')
        self.assertEqual((call.state, call.apply_until, call.verdict['date_checked']), (GrantCall.READY, None, False))

    def test_numbers_not_in_notice_are_dropped_from_lines(self):
        self.scan(FakeLLM({**VERDICT, 'support': '전자책 제작비 300만 원 지원'}))
        self.assertEqual(GrantCall.objects.get(key='kpipa:2167').verdict['support'], '')

    def test_deadline_already_passed_is_old(self):
        self.scan(FakeLLM(VERDICT), today=date(2026, 10, 13))
        self.assertEqual(GrantCall.objects.get(key='kpipa:2167').state, GrantCall.OLD)

    def test_failures_retry_then_give_up_after_three(self):
        llm = FakeLLM('JSON이 아닌 답')
        for _ in range(2):
            with self.assertLogs('intake', 'WARNING'):
                report = self.scan(llm)
            self.assertEqual((GrantCall.objects.get(key='kpipa:2167').state, report.gave_up), (GrantCall.PENDING, []))
        with self.assertLogs('intake', 'WARNING') as logs:
            report = self.scan(llm)
        self.assertIn('grant judge failed: kpipa:2167', logs.output[0])
        call = GrantCall.objects.get(key='kpipa:2167')
        self.assertEqual((call.state, call.tries), (GrantCall.SKIPPED_LLM, 3))
        self.assertIn('3번 읽지 못해', grants.digest(report))

    def test_title_comes_from_view_page_and_attachment_text_reaches_llm(self):
        short = '<ul>' + row('2167', '2026년 제3차 전자책 제작 지원 사업 공…', '26.09.29.') + '</ul>'
        page = view('2026년 제3차 전자책 제작 지원 사업 공고', BODY, files=('붙임1. 공고문.pdf',))
        llm = FakeLLM(VERDICT)
        self.scan(llm, p=pages(**{GRANT_LIST: short, VIEW_2167: page}), get_bytes=lambda url: tiny_pdf('ATTACHED 2026'))
        self.assertEqual(GrantCall.objects.get().title, '2026년 제3차 전자책 제작 지원 사업 공고')
        self.assertIn('ATTACHED 2026', llm.calls[0][1])
        self.assertIn('게시일: 2026-09-29', llm.calls[0][1])

    def test_judges_at_most_three_per_run(self):
        rows = ''.join(row(str(3000 + i), f'2026년 제{i}차 오디오북 제작 지원 사업 공고', '26.09.29.') for i in range(5))
        get = lambda url: '<ul>' + rows + '</ul>' if url == GRANT_LIST else view('오디오북 제작 지원', BODY)
        llm = FakeLLM(VERDICT)
        grants.scan(llm, TODAY, get_text=get, get_bytes=no_bytes, sleep=no_sleep)
        self.assertEqual((len(llm.calls), GrantCall.objects.filter(state=GrantCall.PENDING).count()), (3, 2))

    def test_empty_list_raises(self):
        with self.assertRaises(RuntimeError):
            grants.scan(FakeLLM(VERDICT), TODAY, get_text=lambda url: '<ul></ul>', get_bytes=no_bytes, sleep=no_sleep)
