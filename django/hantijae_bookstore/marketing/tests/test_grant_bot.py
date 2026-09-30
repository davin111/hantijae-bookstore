import json
from datetime import date, datetime, timedelta
from unittest import mock

from django.test import TestCase, override_settings

from intake.models import WorkerState
from marketing import grants
from marketing.bot import Marketing
from marketing.models import Briefing, GrantCall, Proposal
from marketing.tests.fakes import FakeLLM, FakeTG, make_call
from marketing.tests.test_bot import ADMIN, GROUP, FakeHost, cbq
from marketing.timeutil import KST

NOW = datetime(2026, 9, 30, 10, 0, tzinfo=KST)


class Base(TestCase):
    def setUp(self):
        self.tg, self.host = FakeTG(), FakeHost()
        WorkerState.put('marketing_mode', 'live')

    def m(self):
        return Marketing(self.tg, FakeLLM({}), self.host)


class GrantSendTest(Base):
    def test_off_sends_nothing(self):
        make_call()
        self.assertEqual((self.m().send_grants(NOW), self.tg.sent()), (0, []))

    def test_admin_only_previews_once_and_keeps_ready(self):
        WorkerState.put('grant_mode', 'admin_only')
        c = make_call()
        m = self.m()
        m.send_grants(NOW)
        m.send_grants(NOW + timedelta(minutes=1))
        sends = self.tg.sent('send')
        self.assertEqual([(s['chat'], s['buttons']) for s in sends], [(ADMIN, None)])
        self.assertIn('판단: 종이책이 있는 책이면 신청할 수 있어요', sends[0]['text'])
        c.refresh_from_db()
        self.assertEqual((c.state, c.preview_at), (GrantCall.READY, NOW))

    def test_live_sends_one_card_a_day_to_review_room(self):
        WorkerState.put('grant_mode', 'live')
        c = make_call()
        m = self.m()
        self.assertEqual(m.send_grants(NOW), 1)
        card = self.tg.sent('send')[0]
        self.assertEqual(card['chat'], GROUP)
        self.assertTrue(card['text'].startswith('📌 지원사업 공고 — 2026년 제3차 전자책 제작 지원 사업 공고'))
        self.assertIn(f'mk:ga:{c.id}', json.dumps(card['buttons']))
        c.refresh_from_db()
        self.assertEqual((c.state, c.chat_id, c.message_id, c.sent_at), (GrantCall.ANNOUNCED, GROUP, 1001, NOW))
        make_call(no='2170', title='2026년 제4차 전자책 제작 지원 사업 공고')
        self.assertEqual(m.send_grants(NOW + timedelta(hours=2)), 0)   # 오늘은 이미 보냄
        self.assertEqual(m.send_grants(NOW + timedelta(days=1)), 1)

    def test_preview_then_live_goes_to_room(self):
        WorkerState.put('grant_mode', 'admin_only')
        make_call()
        m = self.m()
        m.send_grants(NOW)
        WorkerState.put('grant_mode', 'live')
        m.send_grants(NOW)
        self.assertEqual([s['chat'] for s in self.tg.sent('send')], [ADMIN, GROUP])

    def test_live_grant_mode_but_marketing_admin_only_previews(self):
        WorkerState.put('grant_mode', 'live')
        WorkerState.put('marketing_mode', 'admin_only')
        make_call()
        self.m().send_grants(NOW)
        self.assertEqual(self.tg.sent('send')[0]['chat'], ADMIN)

    def test_quiet_hours_send_nothing(self):
        WorkerState.put('grant_mode', 'live')
        make_call()
        self.assertEqual(self.m().send_grants(datetime(2026, 9, 30, 7, 59, tzinfo=KST)), 0)

    def test_several_new_calls_go_in_one_message_up_to_three(self):
        WorkerState.put('grant_mode', 'live')
        for i, no in enumerate(('2201', '2202', '2203', '2204')):
            make_call(no=no, title=f'공고 {no}', until=date(2026, 10, 12 + i))
        self.m().send_grants(NOW)
        card = self.tg.sent('send')[0]
        self.assertTrue(card['text'].startswith('📌 새 지원사업 공고 3건'))
        self.assertNotIn('공고 2204', card['text'])
        self.assertEqual(len(card['buttons']['inline_keyboard']), 3)
        self.assertEqual(GrantCall.objects.filter(state=GrantCall.READY).count(), 1)

    def test_reminder_two_days_before_deadline_once_after_0930(self):
        WorkerState.put('grant_mode', 'live')
        make_call(state=GrantCall.APPLYING, chat_id=GROUP, message_id=777, sent_at=NOW)
        m = self.m()
        m.send_grants(datetime(2026, 10, 10, 9, 29, tzinfo=KST))
        self.assertEqual(self.tg.sent('send'), [])
        m.send_grants(datetime(2026, 10, 10, 9, 30, tzinfo=KST))
        m.send_grants(datetime(2026, 10, 10, 11, 0, tzinfo=KST))
        sends = self.tg.sent('send')
        self.assertEqual([(s['chat'], s['reply_to']) for s in sends], [(GROUP, 777)])
        self.assertTrue(sends[0]['text'].startswith('⏰ 모레 10월 12일(월) 16시에 신청이 마감돼요'))
        self.assertEqual(GrantCall.objects.get().reminder_message_id, 1001)


@mock.patch('marketing.bot.timezone.now', return_value=NOW)
class GrantButtonTest(Base):
    def test_apply_button_records_and_redraws_card(self, _now):
        c = make_call(state=GrantCall.ANNOUNCED, chat_id=GROUP, message_id=555, sent_at=NOW)
        answer = self.m().handle_callback(f'mk:ga:{c.id}', GROUP, cbq(555), '운영진A')
        self.assertEqual(answer, '마감 이틀 전에 한 번 더 알려 드릴게요')
        c.refresh_from_db()
        self.assertEqual((c.state, c.decided_by), (GrantCall.APPLYING, '운영진A'))
        edit = self.tg.sent('edit')[0]
        self.assertTrue(edit['text'].endswith('✍️ 운영진A: 신청하기로 했어요'))
        self.assertIn(f'mk:gp:{c.id}', json.dumps(edit['buttons']))

    def test_pass_then_change_mind(self, _now):
        c = make_call(state=GrantCall.ANNOUNCED, chat_id=GROUP, message_id=555, sent_at=NOW)
        m = self.m()
        self.assertEqual(m.handle_callback(f'mk:gp:{c.id}', GROUP, cbq(555), '운영진C'), '이번엔 넘길게요')
        m.handle_callback(f'mk:ga:{c.id}', GROUP, cbq(555), '운영진A')
        self.assertEqual(GrantCall.objects.get(pk=c.id).state, GrantCall.APPLYING)

    def test_button_after_deadline_changes_nothing(self, now):
        now.return_value = datetime(2026, 10, 13, 10, 0, tzinfo=KST)
        c = make_call(state=GrantCall.ANNOUNCED, chat_id=GROUP, message_id=555, sent_at=NOW)
        self.assertEqual(self.m().handle_callback(f'mk:ga:{c.id}', GROUP, cbq(555), '운영진A'), '신청 마감이 지났어요')
        self.assertEqual((GrantCall.objects.get(pk=c.id).state, self.tg.sent('edit')), (GrantCall.ANNOUNCED, []))

    def test_reply_to_card_goes_to_admin(self, _now):
        make_call(state=GrantCall.ANNOUNCED, chat_id=GROUP, message_id=555, sent_at=NOW)
        m = self.m()
        self.assertTrue(m.owns_message(GROUP, 555))
        m.handle_reply(GROUP, 555, {'message_id': 9}, '작년에 해 봤는데 서류가 많았어요', '운영진A')
        self.assertEqual(self.host.notes, ['📝 지원사업 카드 답장 — 2026년 제3차 전자책 제작 지원 사업 공고\n'
                                           '운영진A: 작년에 해 봤는데 서류가 많았어요'])
        self.assertEqual([(s['text'], s['reply_to']) for s in self.tg.sent('send')], [('메모 남겼어요.', 9)])
        m.handle_reply(GROUP, 555, {'message_id': 10}, '감사합니다', '운영진A')
        self.assertEqual(len(self.host.notes), 1)


class GrantReminderReplyTest(Base):
    def test_reply_to_reminder_goes_to_admin_and_thanks_stay_quiet(self):
        make_call(state=GrantCall.APPLYING, chat_id=GROUP, message_id=777, reminder_message_id=888, sent_at=NOW)
        m = self.m()
        self.assertTrue(m.owns_message(GROUP, 888))
        m.handle_reply(GROUP, 888, {'message_id': 11}, '오늘 신청서 냈어요', '운영진A')
        self.assertEqual(self.host.notes, ['📝 지원사업 카드 답장 — 2026년 제3차 전자책 제작 지원 사업 공고\n'
                                           '운영진A: 오늘 신청서 냈어요'])
        m.handle_reply(GROUP, 888, {'message_id': 12}, '고마워요', '운영진A')
        self.assertEqual([s['reply_to'] for s in self.tg.sent('send')], [11])


class GrantCommandTest(Base):
    def test_mode_switch_and_status(self):
        m = self.m()
        m.admin_command(ADMIN, '/grant', 'live', now=NOW)
        self.assertEqual(self.tg.sent('send')[-1]['text'], 'grant_mode=live')
        m.admin_command(ADMIN, '/grant', '', now=NOW)
        text = self.tg.sent('send')[-1]['text']
        self.assertTrue(text.startswith('grant_mode=live'))
        self.assertTrue(text.endswith(grants.USAGE))

    def test_now_scans_sends_and_reports(self):
        WorkerState.put('grant_mode', 'admin_only')
        make_call()
        report = grants.ScanReport(new=3, unannounced=['· 2026년 웹소설 공고 — 제목으로 뺌'])
        with mock.patch('marketing.bot.grants.scan', return_value=report) as scan:
            self.m().admin_command(ADMIN, '/grant', 'now', now=NOW)
        scan.assert_called_once()
        texts = [s['text'] for s in self.tg.sent('send')]
        self.assertTrue(texts[1].startswith('🔎 미리보기'))
        self.assertEqual(texts[-1], '새 글 3건\n📋 알리지 않은 지원사업 공고\n· 2026년 웹소설 공고 — 제목으로 뺌\n보낸 메시지 1개')
        self.assertEqual(WorkerState.get('grant_last_scan'), '2026-09-30')


@override_settings(SITE_URL='https://hantijae-bookstore.com')
class GrantBriefingTest(Base):
    def briefing(self, week=date(2026, 10, 5)):
        b = Briefing.objects.create(week_start=week)
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, briefing=b, headline='항목', reason='이유', rank=1)
        return b

    def test_grant_block_is_left_out_when_off_or_failing(self):
        make_call(state=GrantCall.APPLYING, chat_id=GROUP, message_id=555, sent_at=NOW)
        when = datetime(2026, 10, 5, 9, 30, tzinfo=KST)
        self.assertTrue(self.m().send_briefing(self.briefing(), when))   # grant_mode off
        WorkerState.put('grant_mode', 'live')
        with mock.patch('marketing.bot.grants.open_calls', side_effect=RuntimeError('db')), \
                self.assertLogs('intake', 'WARNING'):
            self.assertTrue(self.m().send_briefing(self.briefing(date(2026, 10, 12)), when))
        self.assertTrue(all('지원사업' not in s['text'] for s in self.tg.sent('send')))

    def test_briefing_message_lists_open_calls(self):
        WorkerState.put('grant_mode', 'live')
        make_call(state=GrantCall.APPLYING, chat_id=GROUP, message_id=555, sent_at=NOW)
        b = Briefing.objects.create(week_start=date(2026, 10, 5))
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, briefing=b, headline='항목', reason='이유', rank=1)
        self.assertTrue(self.m().send_briefing(b, datetime(2026, 10, 5, 9, 30, tzinfo=KST)))
        self.assertIn('\n\n📌 지원사업 신청\n· 2026년 제3차 전자책 제작 지원 사업 공고 — 10월 12일(월) 16시 마감 (신청하기로 함)',
                      self.tg.sent('send')[0]['text'])
