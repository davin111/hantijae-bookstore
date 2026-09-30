from datetime import date

from django.test import TestCase

from marketing import board
from marketing.messages import OPEN, POSTED, SKIPPED
from marketing.models import Briefing, Draft, Proposal
from marketing.tests.fakes import FakeTG, make_book


class BoardTest(TestCase):
    def setUp(self):
        self.book = make_book()

    def test_states(self):
        p = Proposal.objects.create(kind=Proposal.KIT, book=self.book, headline='h')
        first = Draft.objects.create(proposal=p, channel=Draft.BLOG, body='1')
        self.assertEqual(board.channel_state(p, Draft.BLOG), OPEN)
        Draft.objects.filter(pk=first.pk).update(status=Draft.SKIPPED)
        self.assertEqual(board.channel_state(p, Draft.BLOG), SKIPPED)
        Draft.objects.create(proposal=p, channel=Draft.BLOG, body='2', version=2, parent=first)
        self.assertEqual(board.channel_state(p, Draft.BLOG), OPEN)  # 새 판이 생기면 다시 열린다
        Draft.objects.filter(proposal=p, version=2).update(status=Draft.POSTED)
        self.assertEqual(board.channel_state(p, Draft.BLOG), POSTED)
        p.status = Proposal.SKIPPED
        self.assertEqual(board.channel_state(p, Draft.INSTAGRAM), SKIPPED)
        p.status = Proposal.ACTED
        self.assertEqual(board.item_state(p), POSTED)

    def test_briefing_hub_uses_shown_order_and_skips_unsent(self):
        b = Briefing.objects.create(week_start=date(2026, 9, 28))
        ps = [Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b, headline=f'h{i}', rank=i)
              for i in (1, 2, 3)]
        self.assertIsNone(board.briefing_hub(b))
        b.chat_id, b.message_id, b.shown = -200, 900, [ps[2].id, ps[0].id]  # 2번은 보류로 빠졌다
        b.save()
        self.assertEqual(board.shown_items(b), [ps[2], ps[0]])
        hub = board.briefing_hub(b)
        texts = [x['text'] for row in hub.buttons['inline_keyboard'] for x in row]
        self.assertEqual((hub.chat_id, hub.message_id, texts[:2]), (-200, 900, ['1번 글 보기', '2번 글 보기']))
        self.assertEqual(hub.buttons['inline_keyboard'][0][0]['callback_data'], f'mk:b:{ps[2].id}')

    def test_hub_of_each_kind_and_refresh(self):
        kit = Proposal.objects.create(kind=Proposal.KIT, book=self.book, headline='h')
        Draft.objects.create(proposal=kit, channel=Draft.INSTAGRAM, body='i', status=Draft.POSTED)
        self.assertIsNone(board.hub_of(kit))  # /kit 미리보기처럼 기록이 없으면 그리지 않는다
        kit.chat_id, kit.message_id, kit.notion = -200, 800, {'url': 'https://notion.test/k'}
        kit.save()
        tg = FakeTG()
        board.refresh(tg, board.hub_of(kit))
        rows = tg.sent('markup')[0]['buttons']['inline_keyboard']
        self.assertEqual(rows[0][0]['text'], '인스타 ✅ 올림')
        self.assertEqual(rows[-1][0]['url'], 'https://notion.test/k')
        now = [Proposal.objects.create(kind=Proposal.NOW, book=self.book, headline=f'n{i}', rank=i, chat_id=-200,
                                       message_id=700) for i in (1, 2)]
        hub = board.hub_of(now[1])
        self.assertEqual([x['text'] for x in hub.buttons['inline_keyboard'][0]], ['1번 글 보기', '2번 글 보기'])
