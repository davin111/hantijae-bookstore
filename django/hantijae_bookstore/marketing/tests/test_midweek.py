from datetime import date, datetime, timedelta

from django.test import TestCase

from intake.models import WorkerState
from marketing import midweek as W
from marketing.bot import Marketing
from marketing.hooks import seed
from marketing.models import BookProfile, Briefing, Draft, HookDate, Proposal, Signal
from marketing.tests.fakes import FakeLLM, FakeTG, make_book
from marketing.tests.test_bot import ADMIN, GROUP, FakeHost
from marketing.timeutil import KST

WED = date(2026, 9, 30)
DAWN = datetime(2026, 9, 30, 5, 30, tzinfo=KST)
SEND = datetime(2026, 9, 30, 9, 30, tzinfo=KST)


def item(cid, headline='『책』 ― 금요일 강연'):
    return {'candidate_id': cid, 'headline': headline, 'reason': '방에서 말씀하신 일이에요.',
            'draft': {'channel': 'instagram', 'title': '', 'body': '글'}}


class MidweekTest(TestCase):
    def setUp(self):
        self.book = make_book(title='내란 앞에서', published=date(2026, 7, 17), isbn='979-11-92455-89-1')
        self.sibwol = make_book(title='시월, 곡비의 노래', published=date(2026, 6, 15), isbn='979-11-92455-88-4',
                                author='10월문학회')
        WorkerState.put('midweek_mode', 'admin_only')
        WorkerState.put('moment_mode', 'admin_only')

    def moment(self, title, day, **detail):
        return Signal.objects.create(kind=Signal.MOMENT, key=f'moment:{title}', book=self.book, title=title, happens_on=day,
                                     relevant=True, detail={'type': 'author', 'status': 'confirmed', 'summary': '요약',
                                                            'book_ids': [self.book.id], **detail})

    def test_moment_items_window(self):
        self.moment('금요일', date(2026, 10, 2))
        self.moment('다음 월요일', date(2026, 10, 5))
        self.moment('다음 화요일', date(2026, 10, 6))
        self.moment('예고', date(2026, 10, 2), type='upcoming')
        self.moment('끝남', date(2026, 10, 1), status='done')
        used = self.moment('씀', date(2026, 10, 2))
        Signal.objects.filter(pk=used.pk).update(used_at=DAWN)
        self.moment('날짜 모름', None, date_unverified=True, date_text='10월 초')
        self.assertEqual([c.signal.title for c in W.moment_items(WED, DAWN)], ['금요일', '다음 월요일'])

    def test_hook_items_skip_sent_briefing_but_not_preview(self):
        seed()
        [c] = W.hook_items(WED)
        self.assertEqual((c.facts['date'], c.books, c.memorial), ('2026-10-01', [self.sibwol], True))
        preview = Briefing.objects.create(week_start=date(2026, 9, 28))
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, briefing=preview, candidate_key=c.id, headline='x')
        self.assertEqual(len(W.hook_items(WED)), 1)
        Briefing.objects.filter(pk=preview.pk).update(sent_at=DAWN)
        self.assertEqual(W.hook_items(WED), [])

    def test_hook_on_next_monday_is_left_to_the_briefing(self):
        h = HookDate.objects.create(name='월요일 기념일', month=10, day=5)
        h.books.add(self.book)
        self.assertEqual(W.hook_items(date(2026, 10, 3)), [])
        self.assertEqual(len(W.hook_items(date(2026, 10, 6))), 0)

    def test_build_mixes_hooks_and_moments_by_mode(self):
        seed()
        m = self.moment('금요일 강연', date(2026, 10, 2))
        hook_id = W.hook_items(WED)[0].id
        llm = FakeLLM({'items': [item(hook_id, '『시월, 곡비의 노래』 ― 10월 1일'), item(f'moment:{m.id}')]})
        made, dropped = W.build(llm, WED, DAWN, 'live')
        self.assertEqual([p.candidate_key for p in made], [hook_id, f'moment:{m.id}'])
        self.assertIn('후보를 모두 쓰세요', llm.calls[0][1])
        self.assertTrue(all(p.kind == Proposal.NOW and p.drafts.count() == 1 for p in made))
        m.refresh_from_db()
        self.assertIsNotNone(m.used_at)
        self.assertEqual(W.build(llm, WED, DAWN, 'live'), ([], []))  # 하루 한 번

    def test_room_gets_moments_only_when_moment_mode_live(self):
        seed()
        self.moment('금요일 강연', date(2026, 10, 2))
        WorkerState.put('midweek_mode', 'live')
        llm = FakeLLM({'items': []})
        W.build(llm, WED, DAWN, 'live')
        self.assertNotIn('moment:', llm.calls[0][1])
        Proposal.objects.all().delete()
        WorkerState.put('moment_mode', 'live')
        llm = FakeLLM({'items': []})
        W.build(llm, WED, DAWN, 'live')
        self.assertIn('moment:', llm.calls[0][1])

    def test_no_build_when_off_on_monday_or_for_quiet_books(self):
        self.moment('금요일 강연', date(2026, 10, 2))
        llm = FakeLLM({'items': []})
        self.assertEqual(W.build(llm, date(2026, 9, 28), DAWN, 'live'), ([], []))  # 월요일
        BookProfile.objects.create(book=self.book, quiet_until=date(2026, 10, 30))
        self.assertEqual(W.build(llm, WED, DAWN, 'live'), ([], []))
        WorkerState.put('midweek_mode', 'off')
        self.assertEqual(W.build(llm, WED, DAWN, 'live'), ([], []))
        self.assertEqual(llm.calls, [])

    def test_release_stale_frees_yesterdays_unsent(self):
        m = self.moment('금요일 강연', date(2026, 10, 2))
        Signal.objects.filter(pk=m.pk).update(used_at=DAWN)
        old = Proposal.objects.create(kind=Proposal.NOW, signal=m, headline='x')
        Proposal.objects.filter(pk=old.pk).update(created_at=DAWN - timedelta(days=1))
        W.release_stale(WED)
        m.refresh_from_db()
        self.assertEqual((Proposal.objects.count(), m.used_at), (0, None))


class MidweekSendTest(TestCase):
    def setUp(self):
        self.tg, self.host = FakeTG(), FakeHost()
        self.m = Marketing(self.tg, FakeLLM({}), self.host)
        self.book = make_book()

    def proposals(self, n=2, at=SEND):
        out = []
        for i in range(1, n + 1):
            p = Proposal.objects.create(kind=Proposal.NOW, book=self.book, headline=f'『책』 ― 계기 {i}', reason='이유',
                                        rank=i)
            Proposal.objects.filter(pk=p.pk).update(created_at=at - timedelta(hours=4))
            Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body=f'글 {i}')
            out.append(p)
        return out

    def test_target_follows_modes(self):
        self.proposals()
        WorkerState.put('marketing_mode', 'live')
        self.assertFalse(self.m.send_midweek(SEND))  # midweek off
        WorkerState.put('midweek_mode', 'admin_only')
        self.assertEqual(W.target(self.host, 'live'), ADMIN)
        WorkerState.put('midweek_mode', 'live')
        self.assertEqual((W.target(self.host, 'live'), W.target(self.host, 'admin_only')), (GROUP, ADMIN))

    def test_sends_one_message_with_buttons_then_nothing(self):
        WorkerState.put('midweek_mode', 'live')
        WorkerState.put('marketing_mode', 'live')
        ps = self.proposals()
        self.assertFalse(self.m.send_midweek(datetime(2026, 9, 30, 7, 0, tzinfo=KST)))  # 조용한 시간
        self.assertTrue(self.m.send_midweek(SEND))
        [msg] = self.tg.sent('send')
        self.assertEqual(msg['chat'], GROUP)
        self.assertIn('<b>이번 주에 앞둔 일이 있어 글을 준비해 뒀어요</b>\n\n<b>1. 『책』 ― 계기 1</b>\n이유', msg['text'])
        self.assertTrue(msg['html'])
        labels = [b['text'] for row in msg['buttons']['inline_keyboard'] for b in row]
        self.assertEqual(labels, ['1번 글 보기', '2번 글 보기', '넘기기'])
        self.assertEqual(set(Proposal.objects.values_list('status', flat=True)), {Proposal.SHOWN})
        self.assertFalse(self.m.send_midweek(SEND + timedelta(hours=1)))
        self.m.handle_callback(f'mk:sn:{ps[0].id}', GROUP, {'id': 'q', 'message': {'message_id': 1001, 'chat': {'id': GROUP}}},
                               '검수자A')
        self.assertEqual(set(Proposal.objects.values_list('status', flat=True)), {Proposal.SKIPPED})

    def test_second_midweek_message_in_a_week_notifies_admin_once(self):
        WorkerState.put('midweek_mode', 'admin_only')
        self.proposals(1, at=SEND - timedelta(days=1))
        self.m.send_midweek(SEND - timedelta(days=1))
        self.assertEqual(self.host.notes, [])
        self.proposals(1)
        self.m.send_midweek(SEND)
        self.proposals(1, at=SEND + timedelta(days=1))
        self.m.send_midweek(SEND + timedelta(days=1))
        self.assertEqual(len(self.host.notes), 1)
        self.assertIn('주중 제안이 두 번째', self.host.notes[0])


class MidweekModeSwitchTest(TestCase):
    def test_room_send_skips_moment_items_unless_moment_mode_live(self):
        tg, host = FakeTG(), FakeHost()
        m = Marketing(tg, FakeLLM({}), host)
        book = make_book()
        for key in ('hook:1:2026-10-01', 'moment:7'):
            p = Proposal.objects.create(kind=Proposal.NOW, book=book, candidate_key=key, headline=key, reason='이유')
            Proposal.objects.filter(pk=p.pk).update(created_at=SEND - timedelta(hours=4))
        WorkerState.put('marketing_mode', 'live')
        WorkerState.put('midweek_mode', 'live')
        WorkerState.put('moment_mode', 'admin_only')
        self.assertTrue(m.send_midweek(SEND))
        self.assertIn('hook:1:2026-10-01', tg.sent('send')[-1]['text'])
        self.assertNotIn('moment:7', tg.sent('send')[-1]['text'])
        self.assertIsNone(Proposal.objects.get(candidate_key='moment:7').sent_at)
