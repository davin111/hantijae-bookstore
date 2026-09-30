from datetime import date, datetime

from django.test import TestCase, override_settings

from intake.models import TelegramChat, WorkerState
from marketing import messages
from marketing import notion_sync as ns
from marketing.bot import Marketing
from marketing.models import Briefing, Draft, Proposal
from marketing.tests.fakes import FakeLLM, FakeNotion, FakeTG, make_book, tg_message
from marketing.timeutil import KST

ADMIN, GROUP = 100, -200
DAY = datetime(2026, 10, 5, 9, 30, tzinfo=KST)


class Host:
    def __init__(self, notion):
        self.notion, self.notes = notion, []

    def _chat(self, kind):
        return ADMIN if kind == TelegramChat.ADMIN else GROUP

    def review_chat_id(self):
        return GROUP

    def notify_admin(self, text):
        self.notes.append(text)


@override_settings(SITE_URL='https://hantijae-bookstore.com')
class BotNotionTest(TestCase):
    def setUp(self):
        WorkerState.put('marketing_mode', 'live')
        WorkerState.put(ns.SWITCH, 'on')
        WorkerState.put(ns.DS, 'ds1')
        self.tg, self.fake, self.book = FakeTG(), FakeNotion(), make_book()
        self.host = Host(self.fake)

    def m(self, reply=None):
        return Marketing(self.tg, FakeLLM(reply or {}), self.host)

    def briefing(self):
        b = Briefing.objects.create(week_start=date(2026, 10, 5))
        p = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b, headline='항목 1', reason='이유',
                                    rank=1)
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='글 1')
        return b, p

    def test_room_briefing_gets_a_page_and_a_notion_button(self):
        b, p = self.briefing()
        self.assertTrue(self.m().send_briefing(b, DAY))
        b.refresh_from_db()
        sent = self.tg.sent('send')[0]
        self.assertEqual(sent['buttons']['inline_keyboard'][-1][0]['url'], b.notion['url'])
        self.assertTrue(sent['html'])
        blue = next(iter(self.fake.blocks.values()))
        self.assertNotIn(messages.BRIEF_GUIDE, blue['callout']['rich_text'][0]['text']['content'])  # 노션엔 안내 줄 없이

    def blue(self):
        """페이지 맨 위 파란 상자(검수 방에 보낸 허브 글)의 글."""
        page = next(iter(self.fake.pages))
        block = self.fake.blocks[self.fake.kids[page][0]]
        return ''.join(r['text']['content'] for r in block['callout']['rich_text'])

    def test_room_briefing_page_shows_the_hub_as_people_read_it(self):
        b, p = self.briefing()
        Proposal.objects.filter(pk=p.pk).update(headline='『<지역서점>』 ― 소식 & 이야기', reason='이유 <짧게>')
        self.m().send_briefing(b, DAY)
        b.refresh_from_db()
        blue = self.blue()
        for tag in ('<b>', '</b>', '&lt;', '&gt;', '&amp;'):
            self.assertNotIn(tag, blue)
        self.assertTrue(blue.startswith('이번 주 홍보 제안 (10월 5일 ~ 10월 11일)'))
        self.assertIn('\n\n1. 『<지역서점>』 ― 소식 & 이야기\n이유 <짧게>', blue)
        self.assertEqual(b.notion['hub_text'], blue)  # 다시 시도할 때도 같은 글
        self.assertIn('<b>', self.tg.sent('send')[0]['text'])  # 텔레그램은 그대로 서식 글

    def test_room_midweek_page_shows_the_hub_as_people_read_it(self):
        WorkerState.put('midweek_mode', 'live')
        p = Proposal.objects.create(kind=Proposal.NOW, book=self.book, headline='『책』 ― 오늘 & 내일', reason='이유', rank=1)
        Proposal.objects.filter(pk=p.pk).update(created_at=DAY)
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='글')
        self.assertTrue(self.m().send_midweek(DAY))
        blue = self.blue()
        self.assertNotIn('<b>', blue)
        self.assertEqual(blue, '이번 주에 앞둔 일이 있어 글을 준비해 뒀어요\n\n1. 『책』 ― 오늘 & 내일\n이유')

    def test_notion_failure_never_blocks_the_briefing(self):
        b, p = self.briefing()
        self.fake.fail['create_page'] = RuntimeError('노션 오류')
        self.assertTrue(self.m().send_briefing(b, DAY))
        b.refresh_from_db()
        self.assertEqual(b.notion['state'], 'pending')
        self.assertEqual(len(self.tg.sent('send')[0]['buttons']['inline_keyboard']), 1)  # 노션 버튼 없음

    def test_admin_preview_and_admin_only_make_no_page(self):
        b, p = self.briefing()
        self.m().send_briefing(b, DAY, chat=ADMIN, record=False)
        WorkerState.put('marketing_mode', 'admin_only')
        self.m().send_briefing(b, DAY)
        self.assertEqual(self.fake.pages, {})

    def test_switch_off_makes_no_page(self):
        WorkerState.put(ns.SWITCH, 'off')
        b, p = self.briefing()
        self.m().send_briefing(b, DAY)
        self.assertEqual(self.fake.pages, {})

    def test_view_sends_the_notion_edit_and_says_so(self):
        b, p = self.briefing()
        self.m().send_briefing(b, DAY)
        box = Draft.objects.get(proposal=p).notion['box']
        self.fake.edit(self.fake.kids[box][0], '노션에서 고친 글 1')
        hub, entities = tg_message(messages.briefing_text(b.week_start, [p]))  # 텔레그램이 돌려주는 모양
        cq = {'id': 'q', 'message': {'message_id': 1001, 'chat': {'id': GROUP}, 'text': hub, 'entities': entities}}
        answer = self.m().handle_callback(f'mk:b:{p.id}', GROUP, cq, 'x')
        self.assertEqual(self.tg.sent('send')[-1]['text'], '노션에서 고친 글 1')
        self.assertEqual(self.tg.sent('send')[-1]['quote_entities'], [{'type': 'bold', 'offset': 0, 'length': 7}])
        self.assertEqual(answer, '1번 인스타 글을 보냈어요 · 노션에서 고친 글이에요')

    def test_posted_records_the_notion_text_and_marks_the_page(self):
        b, p = self.briefing()
        self.m().send_briefing(b, DAY)
        box = Draft.objects.get(proposal=p).notion['box']
        self.fake.edit(self.fake.kids[box][0], '최종 글')
        first = Draft.objects.get(proposal=p, version=1)
        self.m().handle_callback(f'mk:p:{first.id}', GROUP, {'id': 'q', 'message': {'message_id': 5, 'chat': {'id': GROUP}}}, '대표')
        posted = Draft.objects.get(status=Draft.POSTED)
        self.assertEqual((posted.body, posted.origin, posted.posted_by), ('최종 글', Draft.NOTION, '대표'))
        p.refresh_from_db()
        self.assertEqual(self.fake.text_of(p.notion['heading']), '1. 항목 1')  # 버튼 안에서는 노션에 쓰지 않고
        ns.flush(self.host, DAY)  # 워커가 다음 바퀴에 고친다
        self.assertEqual(self.fake.text_of(p.notion['heading']), '✅ 1. 항목 1')

    def test_buttons_leave_notion_to_the_worker(self):
        b, p = self.briefing()
        self.m().send_briefing(b, DAY)
        Proposal.objects.filter(pk=p.pk).update(status=Proposal.ACTED)
        self.fake.calls.clear()
        self.m()._after_status(p)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(len(self.tg.sent('markup')), 1)  # 텔레그램 상황판은 바로 다시 그린다
        b.refresh_from_db()
        self.assertTrue(b.notion['dirty'])

    def test_failed_append_after_a_rewrite_is_left_to_the_worker(self):
        b, p = self.briefing()
        self.m().send_briefing(b, DAY)
        first = Draft.objects.get(proposal=p)
        Draft.objects.filter(pk=first.pk).update(chat_id=GROUP, message_id=777)
        self.fake.fail['append_children'] = RuntimeError('노션 오류')
        with self.assertLogs('intake', 'WARNING'):
            self.m({'title': '', 'body': '둘째 판', 'note': ''}).handle_reply(GROUP, 777, {'message_id': 9}, '짧게요', '대표')
        new = Draft.objects.get(body='둘째 판')
        self.assertEqual(new.notion, {})
        b.refresh_from_db()
        self.assertTrue(b.notion['dirty'])
        ns.flush(self.host, DAY)
        new.refresh_from_db()
        self.assertTrue(new.notion['box'])

    def test_rewrite_reads_notion_first_and_appends_the_new_box(self):
        b, p = self.briefing()
        self.m().send_briefing(b, DAY)
        first = Draft.objects.get(proposal=p)
        box = first.notion['box']
        Draft.objects.filter(pk=first.pk).update(chat_id=GROUP, message_id=777)
        self.fake.edit(self.fake.kids[box][0], '노션 판')
        llm = FakeLLM({'title': '', 'body': '셋째 판', 'note': '줄였어요'})
        Marketing(self.tg, llm, self.host).handle_reply(GROUP, 777, {'message_id': 9}, '짧게요', '대표')
        self.assertIn('노션 판', llm.calls[0][1])
        third = Draft.objects.get(body='셋째 판')
        self.assertEqual((third.version, third.origin), (3, Draft.REWRITE))
        p.refresh_from_db()
        self.assertEqual(self.fake.kids[p.notion['heading']][-1], third.notion['box'])

    def test_kit_card_in_room_gets_a_page(self):
        p = Proposal.objects.create(kind=Proposal.KIT, book=self.book, headline='h',
                                    extra={'blog_exists': True, 'missing_stores': []})
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='인스타')
        self.assertEqual(self.m().send_pending_kits(DAY), 1)
        p.refresh_from_db()
        self.assertEqual(p.notion['state'], 'done')

    def test_mk_notion_switch(self):
        self.assertEqual(self.m()._mk(ADMIN, 'notion off', DAY, DAY.date()), 'marketing_notion=off')
        self.assertIn('marketing_notion=off', self.m()._mk(ADMIN, '', DAY, DAY.date()))
