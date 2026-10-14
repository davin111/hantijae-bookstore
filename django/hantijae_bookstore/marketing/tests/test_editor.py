from datetime import date, datetime, timedelta, timezone
import json

from django.test import TestCase

from intake.llm import LLMError
from intake.models import WorkerState
from marketing.models import CopyNote, Draft, Proposal, Signal
from marketing.tests.fakes import FakeLLM
from marketing.timeutil import KST
from web.blog import BlogPost

try:
    from marketing import editor
except ImportError:
    editor = None


TODAY = date(2026, 10, 16)
NOW = datetime(2026, 10, 16, 5, 30, tzinfo=KST)


def post(day, category='일상'):
    return BlogPost('글 제목', 'https://example.test/blog', day, category)


class EditorTest(TestCase):
    def setUp(self):
        self.assertIsNotNone(editor, '편집 일기 후보·답장 모듈이 필요하다')
        WorkerState.put('editor_mode', 'live')

    def question(self, key='editor:2026-10:2', sent_at=None):
        p = Proposal.objects.create(kind=Proposal.NOW, headline='편집 일기', candidate_key=key, sent_at=sent_at)
        return Draft.objects.create(proposal=p, channel='editor', body='작업 중 기억할 만한 일이 있나요?',
                                    extra={'form': 'questions'})

    def state(self):
        return WorkerState.get('marketing_editor_state')

    def test_period_boundaries_and_kst_midnight(self):
        self.assertEqual(editor.period(date(2026, 10, 15)), ('editor:2026-10:1', date(2026, 10, 1), date(2026, 10, 15)))
        self.assertEqual(editor.period(TODAY), ('editor:2026-10:2', TODAY, date(2026, 10, 31)))
        self.assertEqual(editor.period(date(2028, 2, 29))[2], date(2028, 2, 29))
        self.assertEqual(editor.period(datetime(2026, 10, 15, 15, tzinfo=timezone.utc))[0], 'editor:2026-10:2')

    def test_off_and_sunday_never_make_candidate(self):
        WorkerState.put('editor_mode', 'off')
        self.assertIsNone(editor.prepare(TODAY, [], None, NOW))
        self.assertEqual(self.state()['status'], 'off')
        WorkerState.put('editor_mode', 'live')
        self.assertIsNone(editor.prepare(date(2026, 11, 1), [], None, NOW))
        self.assertEqual(self.state()['status'], 'not_due')

    def test_rss_failure_distinct_from_successful_empty_feed(self):
        self.assertIsNone(editor.prepare(TODAY, None, None, NOW))
        self.assertEqual(self.state()['status'], 'rss_failed')
        candidate, draft = editor.prepare(TODAY, [], None, NOW)
        self.assertEqual(candidate.id, 'editor:2026-10:2')
        self.assertEqual(candidate.books, [])
        self.assertEqual(draft['extra']['form'], 'questions')
        self.assertEqual(Proposal.objects.count(), 0)
        self.assertEqual(self.state()['status'], 'ready')
        self.assertNotIn('room_sent_at', self.state())

    def test_partial_rss_cannot_prove_absence(self):
        self.assertIsNone(editor.prepare(TODAY + timedelta(days=1), [post(TODAY + timedelta(days=1))], None, NOW))
        self.assertEqual(self.state()['status'], 'rss_partial')
        self.assertIsNone(editor.prepare(TODAY, [post(None), post(date(2026, 10, 1))], None, NOW))
        self.assertEqual(self.state()['status'], 'rss_partial')

    def test_nbsp_category_posts_override_incomplete_coverage(self):
        self.assertIsNone(editor.prepare(TODAY, [post(TODAY, ' 편집\u00a0일기 ')], None, NOW))
        self.assertEqual(self.state()['status'], 'posted')
        self.assertEqual(self.state()['posted_on'], TODAY.isoformat())

    def test_first_half_posts_do_not_close_second_half(self):
        result = editor.prepare(TODAY, [post(date(2026, 10, 9), '편집 일기')], None, NOW)
        self.assertIsNotNone(result)
        self.assertEqual(result[0].id, 'editor:2026-10:2')

    def test_existing_generated_candidate_and_preview_are_not_room_success(self):
        q = self.question()
        editor.mark_generated(q.proposal, NOW)
        self.assertIsNone(editor.prepare(TODAY, [], None, NOW))
        self.assertEqual(self.state()['status'], 'generated')
        editor.mark_sent(q.proposal, room=False, now=NOW)
        self.assertEqual(self.state()['status'], 'preview')
        self.assertNotIn('room_sent_at', self.state())
        editor.mark_sent(q.proposal, room=True, now=NOW)
        self.assertIsNone(editor.prepare(TODAY, None, None, NOW))
        self.assertEqual(self.state()['status'], 'sent')
        self.assertEqual(self.state()['room_sent_at'], NOW.isoformat())

    def test_preview_is_reused_for_live_room_without_duplicate_proposal(self):
        q = self.question()
        editor.mark_sent(q.proposal, room=False, now=NOW)
        self.assertEqual(editor.pending(TODAY, room=False), [])
        self.assertEqual([p.pk for p in editor.pending(TODAY, room=True)], [q.proposal_id])
        self.assertFalse(editor.has_room_sent(q.proposal))
        self.assertTrue(editor.can_send(q.proposal, TODAY, [], NOW))
        editor.mark_sent(q.proposal, room=True, now=NOW)
        self.assertEqual(editor.pending(TODAY, room=True), [])
        self.assertEqual(Proposal.objects.count(), 1)

    def test_deleted_generated_row_can_be_rebuilt(self):
        q = self.question()
        editor.mark_generated(q.proposal, NOW)
        q.proposal.delete()
        self.assertIsNotNone(editor.prepare(TODAY, [], None, NOW))

    def test_send_rechecks_posting_rss_failures_and_current_period(self):
        q = self.question()
        self.assertTrue(editor.is_current_period(q.proposal, TODAY))
        self.assertEqual(editor.period_key(TODAY), q.proposal.candidate_key)
        self.assertFalse(editor.can_send(q.proposal, TODAY, None, NOW))
        self.assertEqual(self.state()['status'], 'rss_failed')
        self.assertFalse(editor.can_send(q.proposal, TODAY, [post(None)], NOW))
        self.assertEqual(self.state()['status'], 'rss_partial')
        self.assertTrue(editor.can_send(q.proposal, TODAY, [], NOW))
        self.assertFalse(editor.can_send(q.proposal, TODAY, [post(TODAY, '편집 일기')], NOW))
        self.assertEqual(self.state()['status'], 'posted')
        self.assertFalse(editor.can_send(q.proposal, date(2026, 11, 1), [], NOW))

    def test_confirmed_post_is_not_forgotten_when_feed_rolls_out(self):
        self.assertIsNone(editor.prepare(TODAY, [post(TODAY, '편집 일기')], None, NOW))
        self.assertIsNone(editor.prepare(TODAY + timedelta(days=1), [], None, NOW + timedelta(days=1)))
        self.assertEqual(self.state()['status'], 'posted')

    def test_skipped_original_question_remains_skipped_on_sending(self):
        q = self.question()
        q.status = Draft.SKIPPED
        q.save()
        self.assertFalse(editor.can_send(q.proposal, TODAY, [], NOW))
        self.assertEqual(editor.pending(TODAY, room=True), [])

    def test_late_preview_does_not_erase_room_success(self):
        q = self.question()
        editor.mark_sent(q.proposal, room=True, now=NOW)
        editor.mark_sent(q.proposal, room=False, now=NOW + timedelta(minutes=1))
        self.assertEqual(self.state()['status'], 'sent')

    def test_send_fails_when_editor_mode_turns_off(self):
        q = self.question()
        WorkerState.put('editor_mode', 'off')
        self.assertFalse(editor.can_send(q.proposal, TODAY, [], NOW))

    def test_pending_question_is_not_sent_on_sunday(self):
        q = self.question()
        self.assertFalse(editor.can_send(q.proposal, date(2026, 10, 18), [], NOW + timedelta(days=2)))

    def test_notion_question_copy_accumulates_answers_on_original_root(self):
        original = self.question()
        CopyNote.objects.create(draft=original, text='교정을 마쳤어요.', by='편집장')
        copy = Draft.objects.create(proposal=original.proposal, channel='editor', body='고친 질문',
                                    version=2, origin=Draft.NOTION, parent=original, extra={'form': 'questions'})
        llm = FakeLLM({'title': '작업', 'body': '교정을 마쳤어요. 표지를 확인했어요.'})
        result = editor.create_post(llm, copy, '표지를 확인했어요.', '편집장')
        self.assertEqual(result.parent_id, original.pk)
        self.assertEqual(result.extra['question_id'], original.pk)
        self.assertEqual(original.notes.count(), 2)
        self.assertEqual(copy.notes.count(), 0)
        self.assertEqual(json.loads(llm.calls[0][1])['answers'], ['교정을 마쳤어요.', '표지를 확인했어요.'])

    def test_question_generation_failure_preserves_retry_reason(self):
        signal = Signal.objects.create(kind=Signal.MOMENT, key='failure', title='작업', relevant=True,
                                       detail={'summary': '시안 확인'})
        Signal.objects.filter(pk=signal.pk).update(found_at=NOW)
        with self.assertRaises(LLMError):
            editor.prepare(TODAY, [], FakeLLM('invalid'), NOW)
        self.assertEqual(self.state()['status'], 'failed')
        self.assertEqual(Proposal.objects.count(), 0)

    def test_unidentified_authors_do_not_accumulate_other_unknown_answers(self):
        q = self.question()
        CopyNote.objects.create(draft=q, by='', text='다른사람경험')
        llm = FakeLLM({'title': '작업', 'body': '표지를 확인했어요.'})
        result = editor.create_post(llm, q, '표지를 확인했어요.', '')
        self.assertNotIn('다른사람경험', llm.calls[0][1])
        self.assertEqual(len(result.extra['answer_ids']), 1)

    def test_recent_unanswered_sent_question_defers_then_retries(self):
        q = self.question('editor:2026-10:1', NOW - timedelta(days=3))
        self.assertIsNone(editor.prepare(TODAY, [], None, NOW))
        self.assertEqual(self.state()['status'], 'waiting')
        CopyNote.objects.create(draft=q, text='원고 교정을 마쳤어요.', by='편집장')
        self.assertIsNotNone(editor.prepare(TODAY + timedelta(days=1), [], None, NOW + timedelta(days=1)))

    def test_old_or_skipped_questions_do_not_block(self):
        self.question('old', NOW - timedelta(days=15))
        q = self.question('skipped', NOW - timedelta(days=2))
        q.status = Draft.SKIPPED
        q.save()
        self.assertIsNotNone(editor.prepare(TODAY, [], None, NOW))

    def test_sanitized_signal_prompt_has_no_raw_conversation(self):
        signal = Signal.objects.create(kind=Signal.MOMENT, key='safe', title='표지 작업', relevant=True,
                                       detail={'summary': '표지 시안을 검토함', 'raw': 'PRIVATE_RAW_SENTINEL'})
        Signal.objects.filter(pk=signal.pk).update(found_at=NOW)
        private = Signal.objects.create(kind=Signal.MOMENT, key='private', title='PRIVATE_TITLE',
                                        relevant=True, sensitive=True, detail={'summary': 'PRIVATE_SUMMARY'})
        Signal.objects.filter(pk=private.pk).update(found_at=NOW)
        llm = FakeLLM({'questions': ['시안에서 살펴본 점이 있나요?', '달리 시도한 것이 있나요?', '남기고 싶은 과정이 있나요?']})
        candidate, draft = editor.prepare(TODAY, [], llm, NOW)
        self.assertIn('시안', draft['body'])
        payload = json.loads(llm.calls[0][1])
        self.assertEqual(payload['signals'], [{'title': '표지 작업', 'summary': '표지 시안을 검토함'}])
        self.assertNotIn('PRIVATE', llm.calls[0][1])

    def test_no_material_uses_neutral_questions_without_assumed_emotions(self):
        _, draft = editor.prepare(TODAY, [], None, NOW)
        self.assertEqual(len(draft['extra']['questions']), 3)
        self.assertNotIn('뿌듯', draft['body'])
        self.assertNotIn('감동', draft['body'])

    def test_question_with_invented_number_falls_back(self):
        signal = Signal.objects.create(kind=Signal.MOMENT, key='safe', title='작업', relevant=True,
                                       detail={'summary': '시안 확인'})
        Signal.objects.filter(pk=signal.pk).update(found_at=NOW)
        llm = FakeLLM({'questions': ['3000부 인쇄는 어땠나요?', '시안은 어떤가요?', '표지는 어떤가요?']})
        _, draft = editor.prepare(TODAY, [], llm, NOW)
        self.assertNotIn('3000', draft['body'])
        self.assertIn('검증', self.state()['reason'])

    def test_short_numbers_and_quotes_in_questions_require_source(self):
        signal = Signal.objects.create(kind=Signal.MOMENT, key='shortfacts', title='작업', relevant=True,
                                       detail={'summary': '시안 확인'})
        Signal.objects.filter(pk=signal.pk).update(found_at=NOW)
        for invented in ('2쇄 준비는 어땠나요?', '50명이 온 행사는 어땠나요?', '“고마워요”라는 말이 기억나나요?'):
            with self.subTest(question=invented):
                llm = FakeLLM({'questions': [invented, '기록할 일이 있나요?', '다른 이야기가 있나요?']})
                _, draft = editor.prepare(TODAY, [], llm, NOW)
                self.assertNotIn(invented, draft['body'])
                self.assertIn('검증', self.state()['reason'])

    def test_short_numbers_and_quotes_in_post_require_actual_answers(self):
        q = self.question()
        for invented in ('2쇄를 준비했어요.', '50명이 왔어요.', '“고마워요”라는 말을 들었어요.'):
            with self.subTest(body=invented), self.assertRaises(LLMError):
                editor.create_post(FakeLLM({'title': '작업', 'body': invented}), q, '시안을 확인했어요.', '편집장')
        self.assertEqual(Draft.objects.count(), 1)

    def test_valid_facts_uses_complete_numeric_tokens_and_all_direct_quotes(self):
        source = '12쇄는 1,200부, 50명이 왔고 “고마워요”라고 했어요. 프로필 링크를 고쳤어요.'
        self.assertTrue(editor.valid_facts('12쇄 1200부, 50명. “고마워요”라고 했다. 프로필 링크를 고쳤다.', source))
        self.assertFalse(editor.valid_facts('2쇄를 찍었다.', source))  # 12의 부분 문자열로 인정하지 않음
        self.assertFalse(editor.valid_facts('5명이 왔다.', source))
        self.assertFalse(editor.valid_facts('“고맙죠”라고 했다.', source))
        self.assertFalse(editor.valid_facts("'고맙죠'라고 했다.", source))
        self.assertFalse(editor.valid_facts('‘고맙죠’라고 했다.', source))

    def test_verified_short_facts_survive_question_and_post_generation(self):
        source = '2쇄를 준비했고 50명이 와서 “고마워요”라고 했어요.'
        signal = Signal.objects.create(kind=Signal.MOMENT, key='verifiedfacts', title='작업', relevant=True,
                                       detail={'summary': source})
        Signal.objects.filter(pk=signal.pk).update(found_at=NOW)
        question_text = '2쇄와 50명, “고마워요”라는 말에 대해 더 남길 것이 있나요?'
        _, draft = editor.prepare(TODAY, [], FakeLLM({'questions': [question_text, '다른 일이 있나요?', '더할 말이 있나요?']}), NOW)
        self.assertIn(question_text, draft['body'])
        q = self.question()
        generated = editor.create_post(FakeLLM({'title': '2쇄 준비', 'body': source}), q, source, '편집장')
        self.assertEqual(generated.body, source)

    def test_unfulfilled_period_remains_visible_without_catchup(self):
        editor.defer(date(2026, 10, 15), '세 항목이 가득 참', NOW - timedelta(days=1))
        result = editor.prepare(TODAY, [], None, NOW)
        self.assertEqual(result[0].id, 'editor:2026-10:2')
        self.assertEqual(WorkerState.get('marketing_editor_previous')['status'], 'expired')
        self.assertIn('세 항목', WorkerState.get('marketing_editor_previous')['reason'])

    def test_original_question_accumulates_replies_and_unique_versions(self):
        q = self.question()
        first = editor.create_post(FakeLLM({'title': '교정을 마치고', 'body': '원고 교정을 마쳤어요.', 'note': ''}),
                                   q, '원고 교정을 마쳤어요.', '편집장')
        llm = FakeLLM({'title': '교정을 마치고', 'body': '원고 교정을 마쳤어요. 표지도 확인했어요.', 'note': ''})
        second = editor.create_post(llm, q, '표지도 확인했어요.', '편집장')
        self.assertEqual((first.version, second.version), (2, 3))
        self.assertEqual(second.parent_id, q.pk)
        self.assertEqual(second.extra['form'], 'post')
        self.assertEqual(q.notes.count(), 2)
        q.refresh_from_db()
        self.assertEqual(q.extra['form'], 'questions')
        self.assertEqual(json.loads(llm.calls[0][1])['answers'], ['원고 교정을 마쳤어요.', '표지도 확인했어요.'])

    def test_other_authors_are_not_blended_into_first_person(self):
        q = self.question()
        CopyNote.objects.create(draft=q, text='편집장만의경험', by='편집장')
        llm = FakeLLM({'title': '인쇄소 이야기', 'body': '인쇄소에 다녀왔어요.', 'note': ''})
        result = editor.create_post(llm, q, '인쇄소에 다녀왔어요.', '대표')
        self.assertEqual(result.extra['author'], '대표')
        self.assertNotIn('편집장만의경험', llm.calls[0][1])
        self.assertEqual(q.notes.count(), 2)

    def test_acknowledgement_never_creates_notes_or_posts(self):
        q = self.question()
        self.assertIsNone(editor.create_post(None, q, '넵 감사합니다!', '편집장'))
        self.assertEqual(q.notes.count(), 0)
        self.assertEqual(Draft.objects.count(), 1)

    def test_generated_numbers_and_quotes_require_answer_evidence(self):
        q = self.question()
        for body in ('3000부를 인쇄했어요.', '“이 책이 세상을 바꿀 것입니다”라고 생각했어요.'):
            with self.subTest(body=body), self.assertRaises(LLMError):
                editor.create_post(FakeLLM({'title': '인쇄', 'body': body}), q, '인쇄를 마쳤어요.', '편집장')
        self.assertEqual(Draft.objects.count(), 1)
        self.assertGreater(q.notes.count(), 0)  # 실패해도 운영진의 실제 답을 잃지 않는다

    def test_post_is_not_reinterpreted_as_original_question(self):
        q = self.question()
        q.extra = {'form': 'post'}
        q.save()
        with self.assertRaises(ValueError):
            editor.create_post(None, q, '수정해 주세요.', '편집장')
