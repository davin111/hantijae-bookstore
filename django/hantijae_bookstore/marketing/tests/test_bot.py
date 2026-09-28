from datetime import date, datetime, timedelta
from unittest import mock

from django.test import TestCase, override_settings

from intake.models import TelegramChat, WorkerState
from marketing.bot import KIT_DAILY_CAP, Marketing
from marketing.models import BookProfile, Briefing, CopyNote, Draft, Proposal, WatchQuery
from marketing.tests.fakes import FakeLLM, FakeTG, make_book
from marketing.timeutil import KST

ADMIN, GROUP = 100, -200
DAY = datetime(2026, 9, 28, 10, 0, tzinfo=KST)


class FakeHost:
    def __init__(self):
        self.notes = []

    def _chat(self, kind):
        return ADMIN if kind == TelegramChat.ADMIN else GROUP

    def review_chat_id(self):
        return GROUP

    def notify_admin(self, text):
        self.notes.append(text)


def kit(book):
    p = Proposal.objects.create(kind=Proposal.KIT, book=book, headline=f'『{book.title}』 홍보 자료',
                                extra={'blog_exists': False, 'missing_stores': []})
    Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='인스타 본문')
    Draft.objects.create(proposal=p, channel=Draft.LINKS, body='링크')
    return p


def cbq(message_id=555):
    return {'id': 'q', 'from': {'first_name': '검수자A'}, 'message': {'message_id': message_id, 'chat': {'id': GROUP}}}


@override_settings(SITE_URL='https://hantijae-bookstore.com')
class MarketingBotTest(TestCase):
    def setUp(self):
        self.tg, self.host = FakeTG(), FakeHost()
        self.book = make_book()

    def m(self, reply=None):
        return Marketing(self.tg, FakeLLM(reply or {}), self.host)

    def test_target_chat_follows_mode(self):
        m = self.m()
        self.assertIsNone(m.target_chat())
        WorkerState.put('marketing_mode', 'admin_only')
        self.assertEqual(m.target_chat(), ADMIN)
        WorkerState.put('marketing_mode', 'live')
        self.assertEqual(m.target_chat(), GROUP)

    def test_kit_card_not_sent_twice_and_capped_per_day(self):
        WorkerState.put('marketing_mode', 'live')
        for b in [self.book] + [make_book(title=f'책{i}', isbn=f'979-11-00000-2{i}-1', author=None) for i in range(2)]:
            kit(b)
        m = self.m()
        self.assertEqual(m.send_pending_kits(DAY), 2)
        self.assertEqual(m.send_pending_kits(DAY), 0)
        self.assertEqual(m.send_pending_kits(DAY + timedelta(days=1)), 1)
        self.assertEqual(len(self.tg.sent('send')), 3)  # 표지가 없으면 글 메시지로 보낸다

    def test_quiet_book_kit_waits_and_does_not_use_a_slot(self):
        WorkerState.put('marketing_mode', 'live')
        quiet = kit(self.book)
        BookProfile.objects.create(book=self.book, quiet_until=date(2026, 9, 28))
        others = [kit(make_book(title=f'책{i}', isbn=f'979-11-00000-4{i}-1', author=None)) for i in range(2)]
        m = self.m()
        self.assertEqual(m.send_pending_kits(DAY), 2)
        quiet.refresh_from_db()
        self.assertEqual((quiet.sent_at, quiet.status), (None, Proposal.PROPOSED))
        self.assertEqual(Proposal.objects.filter(pk__in=[o.pk for o in others], sent_at__isnull=False).count(), 2)
        self.assertEqual(m.send_pending_kits(DAY + timedelta(days=1)), 1)
        quiet.refresh_from_db()
        self.assertIsNotNone(quiet.sent_at)

    def test_kit_card_not_sent_in_quiet_hours(self):
        WorkerState.put('marketing_mode', 'live')
        kit(self.book)
        self.assertEqual(self.m().send_pending_kits(datetime(2026, 9, 28, 22, 0, tzinfo=KST)), 0)

    def test_briefing_sent_once_and_items_marked_shown(self):
        WorkerState.put('marketing_mode', 'live')
        b = Briefing.objects.create(week_start=date(2026, 9, 28))
        p = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b, headline='『책』 ― 계기',
                                    reason='이유', rank=1)
        m = self.m()
        self.assertTrue(m.send_briefing(b, DAY))
        self.assertFalse(m.send_briefing(b, DAY))
        p.refresh_from_db()
        self.assertEqual((p.status, p.chat_id), (Proposal.SHOWN, GROUP))
        self.assertTrue(self.tg.sent('send')[0]['text'].startswith('이번 주 홍보 제안'))

    def test_view_callback_sends_latest_version_as_reply(self):
        p = kit(self.book)
        first = p.drafts.get(channel=Draft.INSTAGRAM)
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='고친 본문', version=2, parent=first)
        self.m().handle_callback(f'mk:v:{first.id}', GROUP, cbq(), '검수자A')
        sent = self.tg.sent('send')[0]
        self.assertEqual(sent['reply_to'], 555)
        self.assertIn('고친 본문', sent['text'])
        self.assertTrue(Draft.objects.filter(version=2, message_id__isnull=False).exists())

    def test_posted_callback_records_time_and_actor(self):
        p = kit(self.book)
        d = p.drafts.get(channel=Draft.INSTAGRAM)
        answer = self.m().handle_callback(f'mk:p:{d.id}', GROUP, cbq(), '검수자A')
        d.refresh_from_db()
        p.refresh_from_db()
        self.assertEqual((d.status, d.posted_by, p.status, answer), (Draft.POSTED, '검수자A', Proposal.ACTED, '기록했어요'))
        self.assertIsNotNone(d.posted_at)

    def test_edit_callback_answers_with_hint_only(self):
        d = kit(self.book).drafts.first()
        self.assertIn('답장', self.m().handle_callback(f'mk:e:{d.id}', GROUP, cbq(), 'x'))
        self.assertEqual(self.tg.sent('send'), [])

    def test_skip_week_callback(self):
        b = Briefing.objects.create(week_start=date(2026, 9, 28))
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b, headline='h')
        self.m().handle_callback(f'mk:sw:{b.id}', GROUP, cbq(), 'x')
        self.assertEqual(set(b.items.values_list('status', flat=True)), {Proposal.SKIPPED})

    def test_reply_to_draft_rewrites_as_new_version(self):
        d = kit(self.book).drafts.get(channel=Draft.INSTAGRAM)
        Draft.objects.filter(pk=d.pk).update(chat_id=GROUP, message_id=777)
        m = self.m({'title': '', 'body': '짧아진 인스타 글', 'note': '첫 줄을 줄였어요'})
        self.assertTrue(m.owns_message(GROUP, 777))
        m.handle_reply(GROUP, 777, {'message_id': 9}, '첫 줄이 너무 길어요', '검수자A')
        new = Draft.objects.get(version=2)
        self.assertEqual((new.body, new.parent_id), ('짧아진 인스타 글', d.id))
        self.assertEqual(CopyNote.objects.get().text, '첫 줄이 너무 길어요')
        texts = [c['text'] for c in self.tg.sent('send')]
        self.assertEqual(texts[0], '고치고 있어요. 2~3분쯤 걸려요.')
        self.assertIn('첫 줄을 줄였어요', texts[1])

    def test_reply_to_earlier_copy_of_a_shown_draft_still_rewrites(self):
        d = kit(self.book).drafts.get(channel=Draft.INSTAGRAM)
        m = self.m({'title': '', 'body': '짧아진 인스타 글', 'note': '줄였어요'})
        m.handle_callback(f'mk:v:{d.id}', GROUP, cbq(), '검수자A')
        first_copy = self.tg.next_id
        m.handle_callback(f'mk:v:{d.id}', GROUP, cbq(), '검수자B')
        self.assertTrue(m.owns_message(GROUP, first_copy))
        m.handle_reply(GROUP, first_copy, {'message_id': 9}, '짧게 써 주세요', '검수자A')
        new = Draft.objects.get(version=2)
        self.assertEqual((new.body, new.parent_id), ('짧아진 인스타 글', d.id))

    def test_reply_to_kit_card_asks_for_draft_reply(self):
        p = kit(self.book)
        Proposal.objects.filter(pk=p.pk).update(chat_id=GROUP, message_id=888)
        self.m().handle_reply(GROUP, 888, {'message_id': 9}, '고쳐 주세요', 'x')
        self.assertEqual(self.tg.sent('send')[0]['text'], '고칠 점은 초안 메시지에 답장으로 적어 주세요.')


@override_settings(SITE_URL='https://hantijae-bookstore.com')
class AdminCommandTest(TestCase):
    def setUp(self):
        self.tg, self.host = FakeTG(), FakeHost()
        self.book = make_book()

    def run_cmd(self, cmd, arg='', reply=None, now=DAY):
        with mock.patch('marketing.bot.Marketing.blog_posts', return_value=[]):
            Marketing(self.tg, FakeLLM(reply or {}), self.host).admin_command(ADMIN, cmd, arg, now=now)
        return self.tg.sent('send')[-1]['text']

    def test_mk_sets_mode_and_shows_status(self):
        self.assertEqual(self.run_cmd('/mk', 'admin_only'), 'marketing_mode=admin_only')
        self.assertIn('mode=admin_only', self.run_cmd('/mk'))

    def test_quiet_sets_until_and_rejects_bad_date(self):
        self.assertIn('2026-11-30까지', self.run_cmd('/quiet', '산속으로 2026-11-30 저자 사정'))
        self.assertEqual(BookProfile.objects.get(book=self.book).quiet_reason, '저자 사정')
        self.assertEqual(self.run_cmd('/quiet', '산속으로 2026-13-01'), '날짜가 이상해요')

    def test_hook_add_and_list(self):
        self.assertIn('책 1권', self.run_cmd('/hook', '11-01 산불조심기간 | 나는 산속으로 더 깊이 들어간다'))
        self.assertIn('산불조심기간', self.run_cmd('/hook', 'list'))

    def test_watch_add_list_off(self):
        self.run_cmd('/watch', '정은정')
        w = WatchQuery.objects.get(query='정은정')
        self.assertIn(f'{w.id}. 정은정', self.run_cmd('/watch', 'list'))
        self.assertEqual(self.run_cmd('/watch', f'off {w.id}'), '껐어요')

    def test_watch_links_book_by_author_or_title(self):
        reply = self.run_cmd('/watch', '최정')
        self.assertIn(f'『{self.book.title}』', reply)
        w = WatchQuery.objects.get(query='최정')
        self.assertEqual(w.book, self.book)

        reply2 = self.run_cmd('/watch', self.book.title)
        w2 = WatchQuery.objects.get(query=self.book.title)
        self.assertEqual(w2.book, self.book)
        self.assertIn(f'『{self.book.title}』', reply2)

        reply3 = self.run_cmd('/watch', '없는사람')
        self.assertIn('연결된 책 없음', reply3)

    def test_kit_preview_then_send(self):
        reply = {'blog_body': '', 'instagram': '인스타', 'one_liners': [], 'summary_200': '', 'outreach': [], 'caution': ''}
        text = self.run_cmd('/kit', '산속으로', reply)
        p = Proposal.objects.get(kind=Proposal.KIT)
        self.assertIn(f'/kit send {p.id}', text)
        self.assertEqual(p.status, Proposal.SHOWN)
        self.assertEqual(self.run_cmd('/kit', f'send {p.id}'), '검수 방에 보냈어요')
        p.refresh_from_db()
        self.assertEqual(p.chat_id, GROUP)

    def test_kit_send_refuses_resend(self):
        reply = {'blog_body': '', 'instagram': '인스타', 'one_liners': [], 'summary_200': '', 'outreach': [], 'caution': ''}
        self.run_cmd('/kit', '산속으로', reply)
        p = Proposal.objects.get(kind=Proposal.KIT)
        self.assertEqual(self.run_cmd('/kit', f'send {p.id}'), '검수 방에 보냈어요')
        self.assertEqual(self.run_cmd('/kit', f'send {p.id}'), '이미 검수 방에 보낸 묶음이에요')

    def test_kit_preview_warns_and_send_refuses_for_quiet_book(self):
        BookProfile.objects.create(book=self.book, quiet_until=date(2026, 10, 31))
        reply = {'blog_body': '', 'instagram': '인스타', 'one_liners': [], 'summary_200': '', 'outreach': [], 'caution': ''}
        text = self.run_cmd('/kit', '산속으로', reply)
        self.assertTrue(text.endswith('\n(이 책은 2026-10-31까지 홍보를 쉬는 중이에요)'))
        p = Proposal.objects.get(kind=Proposal.KIT)
        self.assertEqual(self.run_cmd('/kit', f'send {p.id}'), '이 책은 2026-10-31까지 홍보를 쉬는 중이라 보내지 않았어요')
        p.refresh_from_db()
        self.assertIsNone(p.sent_at)

    def test_kit_send_refuses_in_quiet_hours(self):
        reply = {'blog_body': '', 'instagram': '인스타', 'one_liners': [], 'summary_200': '', 'outreach': [], 'caution': ''}
        self.run_cmd('/kit', '산속으로', reply)
        p = Proposal.objects.get(kind=Proposal.KIT)
        text = self.run_cmd('/kit', f'send {p.id}', now=datetime(2026, 9, 28, 22, 0, tzinfo=KST))
        self.assertEqual(text, '조용한 시간(21:00~08:00)이라 보내지 않았어요. 08:00 뒤에 다시 보내 주세요')
        p.refresh_from_db()
        self.assertIsNone(p.chat_id)

    def test_kit_send_respects_daily_cap_for_review_room(self):
        for i in range(2):
            b = make_book(title=f'이미 보낸 책{i}', isbn=f'979-11-00000-3{i}-1', author=None)
            Proposal.objects.create(kind=Proposal.KIT, book=b, headline=f'『{b.title}』 홍보 자료', chat_id=GROUP, sent_at=DAY)
        reply = {'blog_body': '', 'instagram': '인스타', 'one_liners': [], 'summary_200': '', 'outreach': [], 'caution': ''}
        self.run_cmd('/kit', '산속으로', reply)
        p = Proposal.objects.get(kind=Proposal.KIT, book=self.book)
        text = self.run_cmd('/kit', f'send {p.id}')
        self.assertEqual(text, f'오늘은 검수 방에 묶음 카드를 이미 {KIT_DAILY_CAP}장 보냈어요. 내일 다시 보내 주세요')

    def test_brief_preview_does_not_record_then_send(self):
        reply = {'items': [{'candidate_id': f'blog:{self.book.id}', 'headline': '『나는 산속으로 더 깊이 들어간다』 ― 블로그 글',
                            'reason': '아직 블로그 글이 없어요.', 'draft': {'channel': 'blog', 'title': '', 'body': '글'}}]}
        self.assertIn('/brief send', self.run_cmd('/brief', '', reply))
        b = Briefing.objects.get()
        self.assertIsNone(b.sent_at)
        self.assertEqual(self.run_cmd('/brief', 'send'), '검수 방에 보냈어요')
        b.refresh_from_db()
        self.assertEqual(b.chat_id, GROUP)
        self.assertEqual(self.run_cmd('/brief'), '이번 주 브리핑은 이미 보냈어요')
