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

    def _flaky_for(self, *titles):
        send = self.tg.send_message

        def flaky(chat, text, reply_to=None, buttons=None):
            if any(t in text for t in titles):
                raise RuntimeError('telegram 400')
            return send(chat, text, reply_to=reply_to, buttons=buttons)
        return flaky

    def test_failing_kit_send_is_recorded_and_raised_but_other_kit_still_sent(self):
        WorkerState.put('marketing_mode', 'live')
        first, second = kit(self.book), kit(make_book(title='책0', isbn='979-11-00000-50-1', author=None))
        self.tg.send_message = self._flaky_for(self.book.title)
        m = self.m()
        with self.assertLogs('intake', level='ERROR'):
            with self.assertRaises(RuntimeError):
                m.send_pending_kits(DAY)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.sent_at, first.status), (None, Proposal.PROPOSED))
        self.assertEqual(first.extra['send_fail_count'], 1)
        self.assertEqual(first.extra['send_fail_day'], '2026-09-28')
        self.assertIsNotNone(second.sent_at)

    def test_failed_kit_card_not_retried_same_day_next_card_sent_instead(self):
        WorkerState.put('marketing_mode', 'live')
        first = kit(self.book)
        second = kit(make_book(title='책1', isbn='979-11-00000-51-1', author=None))
        third = kit(make_book(title='책2', isbn='979-11-00000-52-1', author=None))
        self.tg.send_message = self._flaky_for(self.book.title)
        m = self.m()
        with self.assertLogs('intake', level='ERROR'):
            with self.assertRaises(RuntimeError):
                m.send_pending_kits(DAY)
        third.refresh_from_db()
        self.assertIsNone(third.sent_at)  # 이번 바퀴엔 방(room) 2자리가 첫째·둘째로 다 찼다

        self.assertEqual(m.send_pending_kits(DAY), 1)  # 같은 날: 실패한 첫째 대신 셋째가 나간다
        first.refresh_from_db()
        second.refresh_from_db()
        third.refresh_from_db()
        self.assertIsNone(first.sent_at)  # 여전히 재시도되지 않음
        self.assertIsNotNone(second.sent_at)
        self.assertIsNotNone(third.sent_at)

    def test_failed_kit_send_retried_next_day(self):
        WorkerState.put('marketing_mode', 'live')
        p = kit(self.book)
        state = {'fail': True}
        send = self.tg.send_message

        def flaky(chat, text, reply_to=None, buttons=None):
            if state['fail']:
                raise RuntimeError('telegram 400')
            return send(chat, text, reply_to=reply_to, buttons=buttons)
        self.tg.send_message = flaky
        m = self.m()
        with self.assertLogs('intake', level='ERROR'):
            with self.assertRaises(RuntimeError):
                m.send_pending_kits(DAY)
        p.refresh_from_db()
        self.assertEqual(p.extra['send_fail_count'], 1)
        state['fail'] = False
        self.assertEqual(m.send_pending_kits(DAY + timedelta(days=1)), 1)
        p.refresh_from_db()
        self.assertIsNotNone(p.sent_at)
        self.assertNotIn('send_fail_day', p.extra)
        self.assertNotIn('send_fail_count', p.extra)
        self.assertEqual((p.extra['blog_exists'], p.extra['missing_stores']), (False, []))  # 다른 extra 값은 그대로

    def test_third_failed_kit_send_notifies_admin_then_stops_trying(self):
        WorkerState.put('marketing_mode', 'live')
        p = kit(self.book)

        def always_fail(chat, text, reply_to=None, buttons=None):
            raise RuntimeError('telegram 400')
        self.tg.send_message = always_fail
        m = self.m()
        for i in range(3):
            with self.assertLogs('intake', level='ERROR'):
                with self.assertRaises(RuntimeError):
                    m.send_pending_kits(DAY + timedelta(days=i))
        p.refresh_from_db()
        self.assertEqual(p.extra['send_fail_count'], 3)
        self.assertEqual(len(self.host.notes), 1)
        self.assertEqual(self.host.notes[0],
                         f'⚠️ 『{self.book.title}』 홍보 묶음 카드를 3번 보내지 못했어요. 확인한 뒤 /kit send {p.id} 로 보내 주세요')
        self.assertEqual(m.send_pending_kits(DAY + timedelta(days=3)), 0)  # 3번째부턴 아예 시도하지 않는다
        p.refresh_from_db()
        self.assertEqual(p.extra['send_fail_count'], 3)
        self.assertEqual(len(self.host.notes), 1)

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

    def test_quiet_book_briefing_item_dropped_at_send_time_and_renumbered(self):
        WorkerState.put('marketing_mode', 'live')
        other = make_book(title='다른책', isbn='979-11-00000-60-1', author=None)
        b = Briefing.objects.create(week_start=date(2026, 9, 28))
        quiet_item = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b,
                                             headline='『책』 ― 계기1', reason='이유1', rank=1)
        kept_item = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=other, briefing=b,
                                            headline='『다른책』 ― 계기2', reason='이유2', rank=2)
        BookProfile.objects.create(book=self.book, quiet_until=date(2026, 9, 28))
        m = self.m()
        self.assertTrue(m.send_briefing(b, DAY))
        quiet_item.refresh_from_db()
        kept_item.refresh_from_db()
        self.assertEqual(quiet_item.status, Proposal.SKIPPED)
        self.assertEqual(kept_item.status, Proposal.SHOWN)
        text = self.tg.sent('send')[0]['text']
        self.assertIn('1. 『다른책』 ― 계기2', text)
        self.assertNotIn('계기1', text)

    def test_quiet_book_acted_item_kept_acted_but_left_out_of_the_sent_message(self):
        WorkerState.put('marketing_mode', 'live')
        other = make_book(title='다른책', isbn='979-11-00000-63-1', author=None)
        b = Briefing.objects.create(week_start=date(2026, 9, 28))
        acted = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b, headline='『책』 ― 계기1',
                                        reason='이유1', rank=1, status=Proposal.ACTED)
        kept = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=other, briefing=b, headline='『다른책』 ― 계기2',
                                       reason='이유2', rank=2)
        BookProfile.objects.create(book=self.book, quiet_until=date(2026, 9, 28))
        m = self.m()
        self.assertTrue(m.send_briefing(b, DAY))
        acted.refresh_from_db()
        kept.refresh_from_db()
        self.assertEqual(acted.status, Proposal.ACTED)  # 상태는 그대로 두지만
        self.assertEqual(kept.status, Proposal.SHOWN)
        text = self.tg.sent('send')[0]['text']
        self.assertNotIn('계기1', text)  # 메시지에는 빠진다
        self.assertIn('1. 『다른책』 ― 계기2', text)

    def test_briefing_not_sent_when_all_items_are_quiet_even_if_one_is_acted(self):
        WorkerState.put('marketing_mode', 'live')
        b = Briefing.objects.create(week_start=date(2026, 9, 28))
        acted = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b, headline='『책』 ― 계기1',
                                        reason='이유1', rank=1, status=Proposal.ACTED)
        BookProfile.objects.create(book=self.book, quiet_until=date(2026, 9, 28))
        m = self.m()
        self.assertFalse(m.send_briefing(b, DAY))
        self.assertEqual(self.tg.sent('send'), [])
        acted.refresh_from_db()
        self.assertEqual(acted.status, Proposal.ACTED)

    def test_briefing_not_sent_when_all_items_are_quiet(self):
        WorkerState.put('marketing_mode', 'live')
        b = Briefing.objects.create(week_start=date(2026, 9, 28))
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b, headline='h', reason='r', rank=1)
        BookProfile.objects.create(book=self.book, quiet_until=date(2026, 9, 28))
        m = self.m()
        self.assertFalse(m.send_briefing(b, DAY))
        self.assertEqual(self.tg.sent('send'), [])
        b.refresh_from_db()
        self.assertIsNone(b.sent_at)

    def test_briefing_preview_excludes_quiet_item_without_changing_status(self):
        other = make_book(title='다른책', isbn='979-11-00000-61-1', author=None)
        b = Briefing.objects.create(week_start=date(2026, 9, 28))
        quiet_item = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b,
                                             headline='『책』 ― 계기1', reason='이유1', rank=1)
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=other, briefing=b,
                                headline='『다른책』 ― 계기2', reason='이유2', rank=2)
        BookProfile.objects.create(book=self.book, quiet_until=date(2026, 9, 28))
        m = self.m()
        self.assertTrue(m.send_briefing(b, DAY, chat=ADMIN, record=False))
        text = self.tg.sent('send')[0]['text']
        self.assertIn('1. 『다른책』 ― 계기2', text)
        self.assertNotIn('계기1', text)
        quiet_item.refresh_from_db()
        self.assertEqual(quiet_item.status, Proposal.PROPOSED)  # 미리보기는 상태를 바꾸지 않는다

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

    def test_rewrite_title_is_clipped(self):
        d = kit(self.book).drafts.get(channel=Draft.INSTAGRAM)
        Draft.objects.filter(pk=d.pk).update(chat_id=GROUP, message_id=777)
        self.m({'title': '가' * 400, 'body': '글', 'note': ''}).handle_reply(GROUP, 777, {'message_id': 9}, '제목', 'x')
        self.assertEqual(len(Draft.objects.get(version=2).title), 300)

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

    def test_thank_you_reply_to_draft_is_skipped_without_rewrite(self):
        d = kit(self.book).drafts.get(channel=Draft.INSTAGRAM)
        Draft.objects.filter(pk=d.pk).update(chat_id=GROUP, message_id=777)
        m = self.m({'title': '', 'body': '안 쓰일 새 글', 'note': ''})
        m.handle_reply(GROUP, 777, {'message_id': 9}, '좋네요', '검수자A')
        self.assertEqual(m.llm.calls, [])
        self.assertEqual(CopyNote.objects.count(), 0)
        self.assertEqual(self.tg.sent('send'), [])
        self.assertEqual(Draft.objects.filter(proposal=d.proposal).count(), 2)  # 새 버전이 생기지 않는다

    def test_edit_request_reply_to_draft_still_rewrites(self):
        d = kit(self.book).drafts.get(channel=Draft.INSTAGRAM)
        Draft.objects.filter(pk=d.pk).update(chat_id=GROUP, message_id=777)
        m = self.m({'title': '', 'body': '짧아진 인스타 글', 'note': ''})
        m.handle_reply(GROUP, 777, {'message_id': 9}, '짧게요', '검수자A')
        self.assertEqual(len(m.llm.calls), 1)
        self.assertTrue(Draft.objects.filter(version=2).exists())

    def test_thank_you_reply_to_kit_card_sends_nothing(self):
        p = kit(self.book)
        Proposal.objects.filter(pk=p.pk).update(chat_id=GROUP, message_id=888)
        self.m().handle_reply(GROUP, 888, {'message_id': 9}, '감사합니다', 'x')
        self.assertEqual(self.tg.sent('send'), [])


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

    def test_mk_social_switch(self):
        self.assertEqual(self.run_cmd('/mk', 'social on'), 'social=on')
        self.assertIn('\nsocial=on\n', self.run_cmd('/mk'))
        self.assertEqual(self.run_cmd('/mk', 'social off'), 'social=off')

    def test_quiet_sets_until_and_rejects_bad_date(self):
        self.assertIn('2026-11-30까지', self.run_cmd('/quiet', '산속으로 2026-11-30 저자 사정'))
        self.assertEqual(BookProfile.objects.get(book=self.book).quiet_reason, '저자 사정')
        self.assertEqual(self.run_cmd('/quiet', '산속으로 2026-13-01'), '날짜가 이상해요')

    def test_quiet_adds_note_when_book_is_in_unsent_weekly_briefing(self):
        b = Briefing.objects.create(week_start=date(2026, 9, 28))
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b, headline='h', reason='r', rank=1)
        reply = self.run_cmd('/quiet', '산속으로 2026-11-30 저자 사정', now=DAY)
        self.assertTrue(reply.endswith('\n이번 주 브리핑에서 이 책 항목은 빼고 보낼게요'))

    def test_quiet_no_note_when_briefing_already_sent_to_review_room(self):
        b = Briefing.objects.create(week_start=date(2026, 9, 28), chat_id=GROUP, message_id=1, sent_at=DAY)
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b, headline='h', reason='r', rank=1)
        reply = self.run_cmd('/quiet', '산속으로 2026-11-30 저자 사정', now=DAY)
        self.assertFalse(reply.endswith('빼고 보낼게요'))

    def test_quiet_no_note_when_book_not_in_this_week_briefing(self):
        reply = self.run_cmd('/quiet', '산속으로 2026-11-30 저자 사정', now=DAY)
        self.assertFalse(reply.endswith('빼고 보낼게요'))

    def test_quiet_no_note_when_date_is_in_the_past(self):
        """/quiet 책 <지난 날짜>는 보류를 끝내는 쪽이라, 브리핑에서 뺄 것도 없다."""
        b = Briefing.objects.create(week_start=date(2026, 9, 28))
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b, headline='h', reason='r', rank=1)
        reply = self.run_cmd('/quiet', '산속으로 2026-09-01 저자 사정', now=DAY)
        self.assertFalse(reply.endswith('빼고 보낼게요'))

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

    def test_manual_kit_build_clears_automatic_build_failure_record(self):
        WorkerState.put('marketing_kit_failures', {str(self.book.id): {'day': '2026-09-27', 'count': 2}})
        reply = {'blog_body': '', 'instagram': '인스타', 'one_liners': [], 'summary_200': '', 'outreach': [], 'caution': ''}
        self.run_cmd('/kit', '산속으로', reply)
        self.assertEqual(WorkerState.get('marketing_kit_failures'), {})

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

    def sent_briefing(self, chat):
        b = Briefing.objects.create(week_start=date(2026, 9, 28), chat_id=chat, message_id=1, sent_at=DAY,
                                    mode='admin_only')
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b, headline='『책』 ― 계기',
                                reason='이유', rank=1, status=Proposal.SHOWN, chat_id=chat)
        return b

    def test_brief_send_forwards_admin_sent_briefing_to_review_room_once(self):
        WorkerState.put('marketing_mode', 'admin_only')
        b = self.sent_briefing(ADMIN)
        later = DAY + timedelta(hours=1)
        self.assertEqual(self.run_cmd('/brief', 'send', now=later), '검수 방에 보냈어요')
        b.refresh_from_db()
        self.assertEqual((b.chat_id, b.sent_at), (GROUP, later))
        self.assertNotEqual(b.message_id, 1)
        self.assertEqual(self.tg.sent('send')[-2]['chat'], GROUP)
        self.assertEqual(self.run_cmd('/brief', 'send'), '이미 검수 방에 보낸 브리핑이에요')

    def test_brief_send_forward_keeps_acted_decisions_and_shows_rest(self):
        WorkerState.put('marketing_mode', 'admin_only')
        b = Briefing.objects.create(week_start=date(2026, 9, 28), chat_id=ADMIN, message_id=1, sent_at=DAY,
                                    mode='admin_only')
        other = make_book(title='다른책', isbn='979-11-00000-62-1', author=None)
        acted = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.book, briefing=b, headline='『책』 ― 계기1',
                                        reason='이유1', rank=1, status=Proposal.ACTED, chat_id=ADMIN)
        shown = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=other, briefing=b, headline='『다른책』 ― 계기2',
                                        reason='이유2', rank=2, status=Proposal.SHOWN, chat_id=ADMIN)
        later = DAY + timedelta(hours=1)
        self.assertEqual(self.run_cmd('/brief', 'send', now=later), '검수 방에 보냈어요')
        acted.refresh_from_db()
        shown.refresh_from_db()
        self.assertEqual(acted.status, Proposal.ACTED)
        self.assertEqual(shown.status, Proposal.SHOWN)
        self.assertEqual((acted.chat_id, shown.chat_id), (GROUP, GROUP))

    def test_brief_send_forward_respects_quiet_hours(self):
        b = self.sent_briefing(ADMIN)
        text = self.run_cmd('/brief', 'send', now=datetime(2026, 9, 28, 22, 0, tzinfo=KST))
        self.assertEqual(text, '보내지 못했어요 (항목 없음 또는 조용한 시간)')
        b.refresh_from_db()
        self.assertEqual(b.chat_id, ADMIN)

    def test_brief_rebuild_allowed_after_admin_only_auto_send(self):
        WorkerState.put('marketing_mode', 'admin_only')
        b = self.sent_briefing(ADMIN)
        reply = {'items': [{'candidate_id': f'blog:{self.book.id}', 'headline': '『나는 산속으로 더 깊이 들어간다』 ― 블로그 글',
                            'reason': '아직 블로그 글이 없어요.', 'draft': {'channel': 'blog', 'title': '', 'body': '글'}}]}
        self.assertIn('/brief send', self.run_cmd('/brief', '', reply))
        self.assertEqual(list(b.items.values_list('candidate_key', flat=True)), [f'blog:{self.book.id}'])

    def test_kit_and_brief_builds_say_they_are_working_first(self):
        reply = {'blog_body': '', 'instagram': '인스타', 'one_liners': [], 'summary_200': '', 'outreach': [], 'caution': ''}
        self.run_cmd('/kit', '산속으로', reply)
        first = self.tg.sent('send')[0]
        self.assertEqual((first['chat'], first['text']), (ADMIN, '만들고 있어요. 몇 분 걸려요.'))
        self.tg.calls.clear()
        self.run_cmd('/brief', '', {'items': []})
        self.assertEqual(self.tg.sent('send')[0]['text'], '만들고 있어요. 몇 분 걸려요.')
        self.tg.calls.clear()
        self.run_cmd('/kit', '없는 책')
        self.assertEqual(len(self.tg.sent('send')), 1)

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


class MomentCommandTest(TestCase):
    def setUp(self):
        self.tg, self.host = FakeTG(), FakeHost()
        self.m = Marketing(self.tg, FakeLLM({'new': []}), self.host)

    def last(self):
        return self.tg.sent('send')[-1]['text']

    def test_status_and_modes(self):
        self.m.admin_command(ADMIN, '/moment', '', now=DAY)
        self.assertIn('moment_mode=off midweek_mode=off', self.last())
        self.assertIn('추출 안 된 기록 0줄', self.last())
        self.m.admin_command(ADMIN, '/moment', 'admin_only', now=DAY)
        self.m.admin_command(ADMIN, '/moment', 'midweek live', now=DAY)
        self.assertEqual((WorkerState.get('moment_mode'), WorkerState.get('midweek_mode')), ('admin_only', 'live'))
        self.m.admin_command(ADMIN, '/moment', 'midweek sometimes', now=DAY)
        self.assertIn('사용법: /moment', self.last())
        self.assertEqual(WorkerState.get('midweek_mode'), 'live')

    def test_list_and_now(self):
        from marketing.models import Signal
        self.m.admin_command(ADMIN, '/moment', 'list', now=DAY)
        self.assertEqual(self.last(), '열린 계기가 없어요')
        Signal.objects.create(kind=Signal.MOMENT, key='moment:x', title='강연', detail={'type': 'author', 'status': 'planned'})
        self.m.admin_command(ADMIN, '/moment', 'list', now=DAY)
        self.assertIn('[author/planned] 날짜 없음 (책 없음) 강연', self.last())
        with mock.patch('marketing.moments.daily', return_value=__import__('marketing.moments', fromlist=['Report']).Report()) as daily:
            self.m.admin_command(ADMIN, '/moment', 'now', now=DAY)
        daily.assert_called_once()
        self.assertEqual(self.last(), '새로 찾은 계기가 없어요')
