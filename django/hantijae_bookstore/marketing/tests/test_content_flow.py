from datetime import date, datetime, timedelta
from unittest.mock import patch

from django.test import TestCase

from intake.models import WorkerState
from marketing.bot import Marketing
from marketing import midweek
from marketing.candidates import Candidate
from marketing.models import Briefing, Draft, DraftMessage, Proposal, Signal
from marketing.tests.fakes import FakeLLM, FakeTG, make_book
from marketing.tests.test_bot import FakeHost, GROUP, cbq
from marketing.timeutil import KST


NOW = datetime(2026, 10, 16, 8, 30, tzinfo=KST)


class ContentFlowTest(TestCase):
    def setUp(self):
        self.tg = FakeTG()
        self.m = Marketing(self.tg, FakeLLM({}), FakeHost())

    def question(self):
        p = Proposal.objects.create(kind=Proposal.NOW, headline='편집 일기', candidate_key='editor:2026-10:2')
        return Draft.objects.create(proposal=p, channel='editor', body='기억에 남은 문장은?', extra={'form': 'questions'})

    def test_new_channel_labels(self):
        self.assertEqual(Draft(channel='recruit').label, '서평단 모집 글')
        self.assertEqual(Draft(channel='editor').label, '편집 후기')

    def test_supplement_is_first_and_both_copies_resolve(self):
        p = Proposal.objects.create(kind=Proposal.NOW, headline='책')
        d = Draft.objects.create(proposal=p, channel='blog', body='복사할 본문', extra={
            'cards': [{'show': '책 표지', 'text': ''}, {'show': '목차', 'text': ''}, {'show': '책 펼친 면', 'text': ''}]})
        self.m._send_draft(d, GROUP)
        sent = self.tg.sent('send')
        self.assertEqual(len(sent), 2)
        self.assertIn('카드', sent[0]['text'])
        self.assertEqual(sent[1]['text'], '복사할 본문')
        d.refresh_from_db()
        self.assertEqual(d.message_id, 1002)
        self.assertEqual(DraftMessage.objects.filter(draft=d).count(), 2)
        self.assertEqual(self.m._draft_for_message(GROUP, 1001), d)

    def test_question_cannot_be_marked_posted_even_by_stale_callback(self):
        d = self.question()
        self.m.handle_callback(f'mk:p:{d.id}', GROUP, cbq(), '운영진A')
        d.refresh_from_db()
        self.assertEqual(d.status, Draft.DRAFT)
        self.assertIsNone(d.posted_at)

    def test_second_reply_to_original_question_still_uses_all_answers(self):
        d = self.question()
        DraftMessage.objects.create(draft=d, chat_id=GROUP, message_id=800)
        self.m.llm = FakeLLM([
            {'title': '교정', 'body': '표지를 고쳤다.', 'note': ''},
            {'title': '교정', 'body': '표지를 고쳤다. 제목도 골랐다.', 'note': ''},
        ])
        self.m.handle_reply(GROUP, 800, {'message_id': 801}, '표지를 고쳤다.', '운영진A')
        self.m.handle_reply(GROUP, 800, {'message_id': 802}, '제목도 골랐다.', '운영진A')
        latest = d.proposal.drafts.order_by('-version', '-id').first()
        self.assertEqual(latest.extra.get('form'), 'post')
        self.assertEqual(latest.version, 3)
        self.assertIn('표지를 고쳤다.', self.m.llm.calls[-1][1])
        self.assertIn('제목도 골랐다.', self.m.llm.calls[-1][1])

    def test_editor_bookless_candidate_survives_filter(self):
        c = Candidate('editor:2026-10:2', 'editor', [], '편집 일기', {}, 4)
        self.assertEqual(midweek._without_quiet([c], NOW.date()), [c])

    def test_send_rechecks_feature_mode(self):
        d = self.question()
        Proposal.objects.filter(pk=d.proposal_id).update(created_at=NOW)
        WorkerState.put('marketing_mode', 'live')
        WorkerState.put('midweek_mode', 'live')
        WorkerState.put('editor_mode', 'off')
        self.assertFalse(self.m.send_midweek(NOW))
        self.assertEqual(self.tg.sent('send'), [])

    def test_sunday_allowed_only_for_dated_mode(self):
        sunday = date(2026, 10, 18)
        self.assertFalse(midweek.build_day(sunday))
        WorkerState.put('dated_mode', 'live')
        self.assertTrue(midweek.build_day(sunday))
        self.assertFalse(midweek.build_day(date(2026, 10, 19)))

    def test_early_send_only_with_today_onsite(self):
        self.assertEqual(midweek.send_at(NOW.date()), (9, 30))
        WorkerState.put('dated_mode', 'live')
        p = Proposal.objects.create(kind=Proposal.NOW, headline='현장', candidate_key='onsite:4:today')
        Proposal.objects.filter(pk=p.pk).update(created_at=NOW)
        self.assertEqual(midweek.send_at(NOW.date()), (8, 30))

    def test_reprint_reserved_during_build_is_still_sent(self):
        book = make_book()
        signal = Signal.objects.create(kind=Signal.MOMENT, key='reprinttest', book=book,
            title='책 2쇄', relevant=True, happens_on=NOW.date(),
            detail={'type': 'reprint', 'status': 'done', 'printing': '2쇄', 'summary': '2쇄를 찍었다.'})
        Signal.objects.filter(pk=signal.pk).update(found_at=NOW)
        for key in ('marketing_mode', 'midweek_mode', 'dated_mode'):
            WorkerState.put(key, 'live')
        llm = FakeLLM({'items': [{'candidate_id': f'reprint:{signal.id}', 'headline': '책 2쇄',
            'reason': '새로 찍은 책', 'draft': {'channel': 'instagram', 'body': '2쇄를 찍었습니다.'}}]})
        made, dropped = midweek.build(llm, NOW.date(), NOW, 'live')
        self.assertEqual(len(made), 1, dropped)
        Proposal.objects.filter(pk=made[0].pk).update(created_at=NOW)
        self.assertTrue(self.m.send_midweek(NOW + timedelta(hours=1)))
        made[0].refresh_from_db()
        self.assertIsNotNone(made[0].sent_at)

    def test_reply_to_editor_post_keeps_that_authors_latest_version(self):
        q = self.question()
        a = Draft.objects.create(proposal=q.proposal, channel='editor', body='A의 교정 경험', version=2,
            parent=q, extra={'form': 'post', 'author': 'A'})
        Draft.objects.create(proposal=q.proposal, channel='editor', body='B의 독자 만남', version=3,
            parent=q, extra={'form': 'post', 'author': 'B'})
        DraftMessage.objects.create(draft=a, chat_id=GROUP, message_id=800)
        self.m.llm = FakeLLM({'title': '교정', 'body': 'A의 교정 경험을 다듬었다.'})
        self.m.handle_reply(GROUP, 800, {'message_id': 801}, '문장을 줄여 주세요.', 'A')
        latest = q.proposal.drafts.order_by('-version', '-id').first()
        self.assertEqual(latest.extra['author'], 'A')
        self.assertEqual(latest.parent_id, a.pk)
        self.assertEqual(latest.version, 4)
        self.assertNotIn('B의 독자 만남', self.m.llm.calls[-1][1])

    def test_stale_bundle_releases_all_reserved_signals(self):
        signals = [Signal.objects.create(kind=Signal.MOMENT, key=f'stale:{i}', title='행사', used_at=NOW) for i in (1, 2)]
        p = Proposal.objects.create(kind=Proposal.NOW, headline='후기', signal=signals[0],
                                    extra={'more_signal_ids': [signals[1].pk]})
        Proposal.objects.filter(pk=p.pk).update(created_at=NOW-timedelta(days=1))
        midweek.release_stale(NOW.date())
        self.assertFalse(Signal.objects.filter(pk__in=[s.pk for s in signals], used_at__isnull=False).exists())

    def test_dated_preview_does_not_consume_room_delivery(self):
        signal = Signal.objects.create(kind=Signal.MOMENT, key='onsite-preview', title='책 축제',
            relevant=True, happens_on=NOW.date(), detail={'type': 'event', 'status': 'confirmed', 'onsite': True})
        p = Proposal.objects.create(kind=Proposal.NOW, headline='책 축제', signal=signal,
                                    candidate_key=f'onsite:{signal.id}:today')
        Proposal.objects.filter(pk=p.pk).update(created_at=NOW)
        Draft.objects.create(proposal=p, channel='instagram', body='오늘 책 축제 현장입니다.')
        WorkerState.put('dated_mode', 'live')
        WorkerState.put('midweek_mode', 'live')
        WorkerState.put('marketing_mode', 'admin_only')
        self.assertTrue(self.m.send_midweek(NOW))
        WorkerState.put('marketing_mode', 'live')
        self.assertTrue(self.m.send_midweek(NOW+timedelta(hours=1)))
        self.assertEqual([m['chat'] for m in self.tg.sent('send')], [100, GROUP])
        self.assertFalse(self.m.send_midweek(NOW+timedelta(hours=2)))

    def test_empty_briefing_can_carry_verified_peer_lines(self):
        WorkerState.put('marketing_mode', 'live')
        b = Briefing.objects.create(week_start=date(2026, 10, 12))
        with patch('marketing.peers.briefing_lines', return_value=['북스톤의 서평단 안내 https://example.com/a']):
            self.assertTrue(self.m.send_briefing(b, NOW+timedelta(hours=1)))
        self.assertIn('다른 출판사는 요즘', self.tg.sent('send')[-1]['text'])
