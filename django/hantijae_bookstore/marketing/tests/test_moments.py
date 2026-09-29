from datetime import date, datetime, timedelta
from unittest import mock

from django.test import TestCase

from context.models import ContextEntry
from intake.llm import LLMError
from marketing import moments as M
from marketing.models import Briefing, Draft, MomentScan, Proposal, Signal, SignalEvidence
from marketing.prompts import build_moment_user
from marketing.tests.fakes import FakeLLM, make_book
from marketing.timeutil import KST

NOW = datetime(2026, 9, 30, 5, 0, tzinfo=KST)  # 수요일 새벽
TODAY = NOW.date()
GROUP = -259


def entry(n, text='', at=None, role='운영진A', **kw):
    at = at or datetime(2026, 9, 29, 10, 0, tzinfo=KST) + timedelta(minutes=n)  # 화요일
    return ContextEntry.objects.create(key=f'tg:{GROUP}:{n}', chat_id=GROUP, message_id=n, at=at, role=role, text=text,
                                       **kw)


def moment(title='강연', book=None, day=None, type_='author', status='planned', found=None, evidence=(), **detail):
    s = Signal.objects.create(kind=Signal.MOMENT, key=f'moment:{title}:{day}', book=book, title=title, happens_on=day,
                              relevant=status != 'cancelled',
                              detail={'type': type_, 'status': status, 'summary': detail.pop('summary', ''), **detail})
    if found:
        Signal.objects.filter(pk=s.pk).update(found_at=found)
        s.refresh_from_db()
    for e in evidence:
        SignalEvidence.objects.create(signal=s, entry=e)
    return s


def new_item(evidence, title='저자 강연', date_='2026-10-02', books=('나는 산속으로 더 깊이 들어간다',), **kw):
    item = {'type': 'author', 'status': 'confirmed', 'title': title, 'summary': kw.pop('summary', '저자가 강연을 한다.'),
            'date': date_, 'date_text': kw.pop('date_text', '금요일'), 'place': kw.pop('place', '대구'),
            'books': list(books), 'evidence': evidence, 'promoted': False, 'sensitive': False}
    item.update(kw)
    return item


class InputTest(TestCase):
    def setUp(self):
        self.book = make_book()

    def test_pending_entries_follow_scan_marks(self):
        a, b = entry(1, '가'), entry(2, '나')
        entry(3, '잊은 글', forgotten=True)
        MomentScan.objects.create(entry=a, changed_at=a.changed_at)
        self.assertEqual(M.pending_entries(), [b])
        ContextEntry.objects.filter(pk=a.pk).update(edited_at=a.created_at + timedelta(minutes=5))
        self.assertEqual(M.pending_entries(), [a, b])

    def test_line_formats(self):
        first = entry(1, '강연 잡혔대요', role='운영진C')
        reply = entry(2, '좋네요', reply_to_id=1, forwarded=True)
        to_bot = entry(3, '고마워요', reply_to_id=99, reply_to_bot=True)
        read = entry(4, '포스터요', media='photo', file_id='f', media_text='[포스터] 10월 2일 저녁 7시',
                     media_read_at=NOW)
        unread = entry(5, '', media='photo', file_id='g')
        old = entry(6, '', media='photo')
        doc = entry(7, '', media='document', media_name='공문.pdf', file_id='d')
        sticker = entry(8, '', media='sticker')
        ids = {(GROUP, 'live', 1): first.id}
        self.assertEqual(M.line(first), f'[#{first.id} 9/29(화) 10:01 운영진C] 강연 잡혔대요')
        self.assertTrue(M.line(reply, ids).endswith(f'좋네요 (↩#{first.id}) (전달)'))
        self.assertTrue(M.line(to_bot, ids).endswith('고마워요 (↩봇)'))
        self.assertIn('[사진] [포스터] 10월 2일 저녁 7시 포스터요', M.line(read))
        self.assertIn('[사진, 아직 못 읽음]', M.line(unread))
        self.assertTrue(M.line(old).endswith('] [사진]'))
        self.assertIn('[파일: 공문.pdf]', M.line(doc))
        self.assertIn('[스티커]', M.line(sticker))
        note = ContextEntry.objects.create(key='notion:b1', source='notion', at=datetime(2026, 9, 28, 9, 0, tzinfo=KST),
                                           heading='『책』 · 12/17 통화', text='저자가 10월 강연')
        self.assertEqual(M.line(note), f'[#{note.id} 노션 · 『책』 · 12/17 통화 · 9/28 수정]\n저자가 10월 강연')

    def test_chunks_split_by_size(self):
        es = [entry(i, '가' * 40) for i in range(1, 6)]
        parts = M.chunks(es, limit=150)
        self.assertEqual([len(p) for p in parts], [2, 2, 1])
        self.assertEqual(sum(parts, []), es)

    def test_context_before_takes_previous_lines_of_same_chat(self):
        old = [entry(i, f'앞 {i}') for i in range(1, 40)]
        ContextEntry.objects.create(key='tg:-1:1', chat_id=-1, message_id=1, at=old[-1].at, text='다른 방')
        new = entry(50, '새 글')
        ctx = M.context_before([new])
        self.assertEqual(len(ctx), 30)
        self.assertEqual(ctx[-1], old[-1])
        self.assertNotIn('다른 방', [e.text for e in ctx])

    def test_open_moments_window(self):
        keep = moment('앞으로', day=TODAY + timedelta(days=3))
        moment('취소', day=TODAY + timedelta(days=3), status='cancelled')
        moment('오래 지남', day=TODAY - timedelta(days=8))
        moment('날짜 없이 오래', found=NOW - timedelta(days=31))
        recent = moment('날짜 없이 최근')
        self.assertEqual(set(M.open_moments(TODAY, NOW)), {keep, recent})
        self.assertIn(f'#{keep.id} [author/planned] 10/3 (책 없음) 앞으로', M.open_line(keep))

    def test_find_book_with_subtitle_and_marks(self):
        sib = make_book(title='시월, 곡비의 노래', isbn='979-11-00000-01-1', author=None)
        for t in ('시월, 곡비의 노래', '『시월, 곡비의 노래』', '시월, 곡비의 노래 ― 10월문학회 시선집', '시월,곡비의노래: 시선집'):
            with self.subTest(t=t):
                self.assertEqual(M.find_book(t), sib)
        self.assertIsNone(M.find_book('없는 책'))

    def test_books_block_and_user_message(self):
        text = M.books_block()
        self.assertIn('『나는 산속으로 더 깊이 들어간다』 — 최정', text)
        user = build_moment_user(TODAY, text, ['#1 [author/planned] …'], '[#1 …] 앞', '[#2 …] 새')
        for part in ('2026-09-30(수요일)', '<책 목록>', '<열린 계기>', '#1 [author/planned]', '<앞 대화 — 참고만>',
                     '<새 기록>', '[#2 …] 새'):
            self.assertIn(part, user)


class RunTest(TestCase):
    def setUp(self):
        self.book = make_book()

    def run_with(self, reply, **kw):
        return M.run(FakeLLM(reply), NOW, **kw)

    def test_new_moment_saved_with_evidence_book_and_redaction(self):
        e = entry(1, '금요일에 대구에서 저자 강연 있어요. 문의 010-1234-5678')
        r = self.run_with({'new': [new_item([e.id], summary='문의는 010-1234-5678로 받는다.')]})
        [s] = r.new
        self.assertEqual((s.kind, s.book, s.happens_on, s.relevant), (Signal.MOMENT, self.book, date(2026, 10, 2), True))
        self.assertEqual((s.detail['type'], s.detail['status'], s.detail['summary']),
                         ('author', 'confirmed', '문의는 [전화]로 받는다.'))
        self.assertEqual((s.detail['book_ids'], s.detail['sources'], s.detail['date_unverified']),
                         ([self.book.id], ['telegram'], False))
        self.assertEqual(list(s.evidence.values_list('entry_id', flat=True)), [e.id])
        self.assertEqual(MomentScan.objects.get(entry=e).changed_at, e.changed_at)
        self.assertEqual(M.pending_entries(), [])

    def test_drops_unknown_evidence_type_and_update_id(self):
        e = entry(1, '금요일 강연')
        r = self.run_with({'new': [new_item([999]), new_item([e.id], type='gossip')],
                           'updates': [{'id': 12345, 'status': 'done', 'evidence': [e.id]}]})
        self.assertEqual(r.new, [])
        self.assertEqual(len(r.dropped), 3)
        self.assertTrue(any('근거 없음' in d for d in r.dropped))
        self.assertTrue(any('없는 계기 번호' in d for d in r.dropped))

    def test_invented_number_dropped_but_iso_dates_allowed(self):
        e = entry(1, '금요일에 강연')
        r = self.run_with({'new': [new_item([e.id], title='강연 300명', summary='2026-10-02에 강연'),
                                   new_item([e.id], title='강연', summary='2026-10-02 금요일에 강연한다.')]})
        self.assertEqual([s.title for s in r.new], ['강연'])
        self.assertIn('자료에 없는 숫자 300', r.dropped[0])

    def test_unverified_date_is_cleared_and_flagged(self):
        e = entry(1, '강연이 잡혔대요')
        [s] = self.run_with({'new': [new_item([e.id], date_='2026-10-17', date_text='')]}).new
        self.assertEqual((s.happens_on, s.detail['date_unverified'], s.detail['date_text']), (None, True, '2026-10-17'))

    def test_old_event_dropped(self):
        e = entry(1, '9월 20일에 북토크 했어요')
        r = self.run_with({'new': [new_item([e.id], date_='2026-09-20', date_text='9월 20일')]})
        self.assertEqual(r.new, [])
        self.assertIn('지난 일', r.dropped[0])

    def test_duplicate_new_merges_into_open_moment(self):
        first = entry(1, '금요일 강연')
        s = moment('저자 강연', book=self.book, day=date(2026, 10, 2), evidence=[first], summary='강연')
        e = entry(2, '금요일 강연 장소는 대구래요')
        r = self.run_with({'new': [new_item([e.id], date_='2026-10-02', place='대구 ○○서점', summary='장소가 정해졌다.')]})
        self.assertEqual(r.new, [])
        self.assertEqual(Signal.objects.count(), 1)
        s.refresh_from_db()
        self.assertEqual((s.detail['place'], s.evidence.count()), ('대구 ○○서점', 2))
        self.assertIn('근거 +1', r.changed[0])

    def test_update_cancel_and_date_change(self):
        first = entry(1, '금요일 강연')
        s = moment('저자 강연', book=self.book, day=date(2026, 10, 2), evidence=[first])
        e = entry(2, '강연이 다음 주 금요일로 밀렸어요')
        r = self.run_with({'updates': [{'id': s.id, 'date': '2026-10-09', 'evidence': [e.id]}]})
        s.refresh_from_db()
        self.assertEqual(s.happens_on, date(2026, 10, 9))
        self.assertIn('날짜 10/2 → 10/9', r.changed[0])
        e2 = entry(3, '강연 취소됐대요')
        self.run_with({'updates': [{'id': s.id, 'status': 'cancelled', 'evidence': [e2.id]}]})
        s.refresh_from_db()
        self.assertEqual((s.detail['status'], s.relevant, s.evidence.count()), ('cancelled', False, 3))

    def test_unverified_update_does_not_erase_known_date(self):
        first = entry(1, '금요일 강연')
        s = moment('저자 강연', book=self.book, day=date(2026, 10, 2), evidence=[first])
        e = entry(2, '강연 시간 바뀜')
        self.run_with({'updates': [{'id': s.id, 'date': '2026-11-20', 'evidence': [e.id]}]})
        s.refresh_from_db()
        self.assertEqual(s.happens_on, date(2026, 10, 2))

    def test_failed_chunk_keeps_earlier_marks(self):
        a, b = entry(1, '가' * 50), entry(2, '나' * 50)

        class Flaky:
            calls = 0

            def complete(self, system, user, attachments=()):
                Flaky.calls += 1
                if Flaky.calls > 1:
                    raise LLMError('boom')
                return '{"new": []}'
        with mock.patch.object(M, 'CHUNK_CHARS', 80):
            r = M.run(Flaky(), NOW)
        self.assertTrue(MomentScan.objects.filter(entry=a).exists())
        self.assertFalse(MomentScan.objects.filter(entry=b).exists())
        self.assertIn('추출 중단', r.errors[0])
        self.assertEqual(r.left, 1)

    def test_max_chunks_leaves_rest_for_later(self):
        for i in range(1, 4):
            entry(i, '가' * 50)
        with mock.patch.object(M, 'CHUNK_CHARS', 80):
            r = M.run(FakeLLM({'new': []}), NOW, max_chunks=2)
        self.assertEqual((r.left, MomentScan.objects.count()), (1, 2))

    def test_dry_run_writes_nothing(self):
        e = entry(1, '금요일에 강연')
        entry(2, '', media='sticker')
        r = self.run_with({'new': [new_item([e.id])]}, dry_run=True)
        self.assertEqual((Signal.objects.count(), MomentScan.objects.count()), (0, 0))
        self.assertIn('+ [author/confirmed] 2026-10-02 『나는 산속으로 더 깊이 들어간다』 저자 강연', r.preview[0])

    def test_trivial_only_day_skips_llm(self):
        entry(1, '', media='sticker')
        entry(2, '   ')
        waiting = entry(3, '', media='photo', file_id='f')
        llm = FakeLLM({'new': []})
        M.run(llm, NOW)
        self.assertEqual(llm.calls, [])
        self.assertEqual(MomentScan.objects.count(), 2)
        self.assertEqual(M.pending_entries(), [waiting])

    def test_evidence_formats_and_subtitled_title(self):
        sib = make_book(title='시월, 곡비의 노래', isbn='979-11-00000-01-1', author=None)
        e = entry(1, '금요일 낭독회')
        [s] = self.run_with({'new': [new_item([str(e.id), f'#{e.id}'], type='event',
                                              books=['『시월, 곡비의 노래』 ― 10월문학회 시선집', '없는 책'])]}).new
        self.assertEqual((s.book, s.detail['book_hint']), (sib, '없는 책'))
        self.assertEqual(s.evidence.count(), 1)


class SweepAndDigestTest(TestCase):
    def setUp(self):
        self.book = make_book()

    def test_sweep_drops_moments_with_forgotten_or_no_evidence(self):
        a, b = entry(1, '가'), entry(2, '나')
        keep = moment('남김', book=self.book, evidence=[a])
        moment('잊음', book=self.book, evidence=[a, b])
        moment('근거 없음', book=self.book)
        ContextEntry.objects.filter(pk=b.pk).update(forgotten=True)
        self.assertEqual(M.sweep(), 2)
        self.assertEqual(list(Signal.objects.all()), [keep])

    def test_drop_removes_unsent_proposals_keeps_sent(self):
        e = entry(1, '가')
        s = moment('강연', book=self.book, evidence=[e])
        unsent_brief = Briefing.objects.create(week_start=date(2026, 9, 28))
        sent_brief = Briefing.objects.create(week_start=date(2026, 9, 21), sent_at=NOW)
        p1 = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, briefing=unsent_brief, signal=s, headline='a')
        p2 = Proposal.objects.create(kind=Proposal.NOW, signal=s, headline='b')
        p3 = Proposal.objects.create(kind=Proposal.NOW, signal=s, headline='c', sent_at=NOW)
        p4 = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, briefing=sent_brief, signal=s, headline='d')
        Draft.objects.create(proposal=p1, channel=Draft.INSTAGRAM, body='글')
        self.assertEqual(M.drop_for_entries([e.id]), 1)
        self.assertFalse(Signal.objects.exists())
        self.assertEqual(set(Proposal.objects.values_list('id', flat=True)), {p3.id, p4.id})
        self.assertEqual(set(Proposal.objects.values_list('signal', flat=True)), {None})
        self.assertFalse(Draft.objects.filter(proposal_id=p1.id).exists())
        self.assertNotIn(p2.id, Proposal.objects.values_list('id', flat=True))

    def test_forget_after_sent_keeps_sent_proposal_usable(self):
        from marketing.bot import Marketing
        from marketing.tests.fakes import FakeTG
        from marketing.tests.test_bot import FakeHost, cbq
        e = entry(1, '가')
        s = moment('강연', book=self.book, evidence=[e])
        p = Proposal.objects.create(kind=Proposal.NOW, book=self.book, signal=s, headline='a', sent_at=NOW,
                                    chat_id=-200, message_id=555)
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='인스타 글')
        M.drop_for_entries([e.id])
        tg = FakeTG()
        Marketing(tg, FakeLLM({}), FakeHost()).handle_callback(f'mk:b:{p.id}', -200, cbq(), '검수자A')
        self.assertIn('인스타 글', tg.sent('send')[-1]['text'])

    def test_digest_lines(self):
        self.assertEqual(M.digest(M.Report(), NOW), '')
        e = entry(1, '가')
        calm = moment('강연', book=self.book, day=date(2026, 10, 2), evidence=[e])
        vague = moment('북토크', book=self.book, evidence=[e], date_unverified=True, date_text='10월 중순')
        hot = moment('저자 입원', book=self.book, evidence=[e])
        hot.sensitive = True
        r = M.Report(new=[calm, vague, hot], changed=['『책』 강연: 취소'], dropped=['x: 근거 없음'], photos=2, notion=1,
                     errors=['노션 읽기 실패: HTTPError'], left=3)
        text = M.digest(r, NOW)
        for part in ('🔎 대화 속 계기 (9/30 05:00)', '새로 3 · 바뀜 1 · 버림 1',
                     f'+ 『나는 산속으로 더 깊이 들어간다』 10/2 저자 활동 — 강연 (#{e.id})', '~ 『책』 강연: 취소',
                     '- 버림: x: 근거 없음', '? 『나는 산속으로 더 깊이 들어간다』 북토크: 날짜 확인 못 함 "10월 중순"',
                     '🔕 민감 1건', '/quiet 나는 산속으로 더 깊이 YYYY-MM-DD 이유', '사진 2장 · 노션 구역 1개 · 남은 기록 3줄은 다음에',
                     '⚠️ 노션 읽기 실패: HTTPError'):
            self.assertIn(part, text)
        self.assertNotIn('+ 『나는 산속으로 더 깊이 들어간다』 날짜 없음 저자 활동 — 저자 입원', text)


class PhotoAskTest(TestCase):
    def test_photo_ask_sends_jpeg_attachments(self):
        class Recorder:
            def complete(self, system, user, attachments=()):
                self.attachments = list(attachments)
                return '{"items": []}'
        llm = Recorder()
        self.assertEqual(M.photo_ask(llm)('sys', 'user', [b'a', b'b']), {'items': []})
        self.assertEqual([(a.kind, a.media_type, a.data) for a in llm.attachments],
                         [('image', 'image/jpeg', b'a'), ('image', 'image/jpeg', b'b')])
