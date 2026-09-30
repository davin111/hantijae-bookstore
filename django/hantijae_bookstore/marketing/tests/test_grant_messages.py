from datetime import date, datetime

from django.test import TestCase

from marketing import grants, messages
from marketing.models import GrantCall
from marketing.tests.fakes import make_call
from marketing.timeutil import KST

TODAY = date(2026, 9, 30)
NOW = datetime(2026, 9, 30, 10, 0, tzinfo=KST)
CARD = ('📌 지원사업 공고 — 2026년 제3차 전자책 제작 지원 사업 공고\n'
        '신청 10월 2일(금) ~ 10월 12일(월) 16시\n'
        '지원: 전자책 제작비 지원(출판사당 10종까지)\n'
        '준비: 출판유통통합전산망 가입, 종이책 정보 등록\n'
        '공고: https://www.kpipa.or.kr/p/g1_2/2167')


class CardTextTest(TestCase):
    def test_single_card(self):
        c = make_call()
        self.assertEqual(messages.grant_card_text([c]), CARD)
        self.assertEqual(messages.grant_buttons([c]), {'inline_keyboard': [[
            {'text': '신청할게요', 'callback_data': f'mk:ga:{c.id}'},
            {'text': '이번엔 넘기기', 'callback_data': f'mk:gp:{c.id}'}]]})

    def test_decision_line_after_button(self):
        c = make_call(state=GrantCall.APPLYING, decided_by='운영진A')
        self.assertTrue(messages.grant_card_text([c]).endswith('\n✍️ 운영진A: 신청하기로 했어요'))
        c = make_call(no='2168', state=GrantCall.PASSED, decided_by='운영진C')
        self.assertTrue(messages.grant_card_text([c]).endswith('\n👌 운영진C: 이번엔 넘겨요'))

    def test_unknown_deadline_and_no_start(self):
        c = make_call(until=None, verdict={'apply_from': '', 'support': '', 'prep': ''})
        self.assertEqual(messages.grant_card_text([c]).split('\n')[1:],
                         ['신청 기간은 공고에서 확인해 주세요', '공고: https://www.kpipa.or.kr/p/g1_2/2167'])
        c = make_call(no='2169', verdict={'apply_from': '', 'until_time': '09:30'})
        self.assertEqual(messages.grant_card_text([c]).split('\n')[1], '신청 마감 10월 12일(월) 9시 30분')

    def test_several_calls_are_numbered_with_buttons_per_row(self):
        a, b = make_call(), make_call(no='2170', title='2026년 제2차 오디오북 제작 지원 사업 신청 공고')
        text = messages.grant_card_text([a, b])
        self.assertTrue(text.startswith('📌 새 지원사업 공고 2건\n\n1. 2026년 제3차 전자책 제작 지원 사업 공고\n'))
        self.assertIn('\n\n2. 2026년 제2차 오디오북 제작 지원 사업 신청 공고\n', text)
        rows = messages.grant_buttons([a, b])['inline_keyboard']
        self.assertEqual([[x['text'] for x in r] for r in rows], [['1번 신청할게요', '1번 넘기기'], ['2번 신청할게요', '2번 넘기기']])

    def test_preview_shows_llm_reason_and_no_buttons_needed(self):
        c = make_call(until=None)
        text = messages.grant_preview_text([c])
        self.assertTrue(text.startswith('🔎 미리보기 — 검수 방에는 /grant live 뒤에 가요\n\n📌 지원사업 공고 —'))
        self.assertTrue(text.endswith('판단: 종이책이 있는 책이면 신청할 수 있어요 (마감일 확인 못 함)'))

    def test_reminder(self):
        self.assertEqual(messages.grant_reminder_text(make_call()),
                         '⏰ 모레 10월 12일(월) 16시에 신청이 마감돼요 — 2026년 제3차 전자책 제작 지원 사업 공고\n'
                         '공고: https://www.kpipa.or.kr/p/g1_2/2167')

    def test_briefing_block(self):
        ps = [type('P', (), {'headline': '항목', 'reason': '이유', 'extra': {}})()]
        lines = ['· 2026년 제3차 전자책 제작 지원 사업 공고 — 10월 12일(월) 16시 마감 (신청하기로 함)']
        text = messages.briefing_text(date(2026, 10, 5), ps, measure='측정 줄', grants=lines)
        self.assertTrue(text.endswith('\n\n📌 지원사업 신청\n' + lines[0] + '\n\n측정 줄'))
        self.assertNotIn('지원사업', messages.briefing_text(date(2026, 10, 5), ps))
        c = make_call(state=GrantCall.APPLYING)
        self.assertEqual(messages.grant_briefing_lines([c]), lines)
        self.assertEqual(messages.grant_briefing_lines([make_call(no='2171', until=None, state=GrantCall.ANNOUNCED)]),
                         ['· 2026년 제3차 전자책 제작 지원 사업 공고 — 마감은 공고에서 확인'])


class QueryTest(TestCase):
    def test_to_send_orders_by_deadline_and_retires_past_deadline(self):
        late = make_call(no='1', until=date(2026, 10, 20))
        unknown = make_call(no='2', until=None)
        soon = make_call(no='3', until=date(2026, 10, 5))
        make_call(no='4', state=GrantCall.ANNOUNCED)
        self.assertEqual([c.key for c in grants.to_send(TODAY)], [soon.key, late.key, unknown.key])

    def test_to_send_retires_past_deadline(self):
        gone = make_call(no='5', until=date(2026, 9, 29))
        self.assertEqual(grants.to_send(TODAY), [])
        gone.refresh_from_db()
        self.assertEqual(gone.state, GrantCall.OLD)

    def test_open_calls_for_briefing(self):
        applying = make_call(no='1', state=GrantCall.APPLYING, until=date(2026, 10, 12))
        announced = make_call(no='2', state=GrantCall.ANNOUNCED, until=date(2026, 10, 8))
        recent_unknown = make_call(no='3', state=GrantCall.ANNOUNCED, until=None, posted=date(2026, 9, 20))
        make_call(no='4', state=GrantCall.ANNOUNCED, until=None, posted=date(2026, 9, 1))   # 21일 넘은 마감 모름
        make_call(no='5', state=GrantCall.PASSED)
        make_call(no='6', state=GrantCall.ANNOUNCED, until=date(2026, 9, 29))             # 마감 지남
        self.assertEqual([c.key for c in grants.open_calls(TODAY)], [announced.key, applying.key, recent_unknown.key])

    def test_due_reminders_two_days_before_once(self):
        c = make_call(state=GrantCall.APPLYING, until=date(2026, 10, 12), chat_id=-1, message_id=5)
        make_call(no='2', state=GrantCall.ANNOUNCED, until=date(2026, 10, 12), chat_id=-1, message_id=5)
        self.assertEqual(grants.due_reminders(date(2026, 10, 9)), [])
        self.assertEqual(grants.due_reminders(date(2026, 10, 10)), [c])
        GrantCall.objects.filter(pk=c.pk).update(reminded_at=NOW)
        self.assertEqual(grants.due_reminders(date(2026, 10, 10)), [])

    def test_card_calls_keep_card_order(self):
        a = make_call(no='1', until=date(2026, 10, 5), chat_id=-1, message_id=9)
        b = make_call(no='2', until=date(2026, 10, 12), chat_id=-1, message_id=9)
        GrantCall.objects.filter(pk=a.pk).update(state=GrantCall.APPLYING)
        self.assertEqual([c.key for c in grants.card_calls(-1, 9)], [a.key, b.key])


class DecideTest(TestCase):
    def test_apply_pass_and_change_mind(self):
        c = make_call(state=GrantCall.ANNOUNCED)
        call, answer = grants.decide(c.id, True, '운영진A', NOW)
        self.assertEqual((call.state, call.decided_by, answer), (GrantCall.APPLYING, '운영진A', '마감 이틀 전에 한 번 더 알려 드릴게요'))
        call, answer = grants.decide(c.id, False, '운영진C', NOW)
        self.assertEqual((call.state, call.decided_by, answer), (GrantCall.PASSED, '운영진C', '이번엔 넘길게요'))

    def test_close_to_deadline_or_unknown_deadline_does_not_promise_reminder(self):
        c = make_call(state=GrantCall.ANNOUNCED, until=date(2026, 10, 1))
        self.assertEqual(grants.decide(c.id, True, '운영진A', NOW)[1], '신청하기로 적어 뒀어요')
        u = make_call(no='2', state=GrantCall.ANNOUNCED, until=None)
        self.assertEqual(grants.decide(u.id, True, '운영진A', NOW)[1], '신청하기로 적어 뒀어요')

    def test_after_deadline_or_not_open(self):
        c = make_call(state=GrantCall.ANNOUNCED, until=date(2026, 9, 29))
        self.assertEqual(grants.decide(c.id, True, '운영진A', NOW), (None, '신청 마감이 지났어요'))
        self.assertEqual(GrantCall.objects.get(pk=c.id).state, GrantCall.ANNOUNCED)
        old = make_call(no='2', state=GrantCall.OLD)
        self.assertEqual(grants.decide(old.id, True, '운영진A', NOW), (None, '이미 정리된 공고예요'))
        self.assertEqual(grants.decide(99999, True, '운영진A', NOW), (None, '이미 정리된 공고예요'))

    def test_status_text(self):
        make_call(state=GrantCall.APPLYING)
        text = grants.status_text(TODAY)
        self.assertTrue(text.startswith('grant_mode=off\ngrant_last_scan=None\n'))
        self.assertIn('신청 · 2026년 제3차 전자책 제작 지원 사업 공고 · 2026-10-12', text)
        self.assertEqual(grants.USAGE.count('/grant'), 2)
