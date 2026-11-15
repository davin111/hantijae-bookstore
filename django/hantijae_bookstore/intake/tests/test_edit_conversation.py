import json
from unittest import mock

from django.test import TestCase, override_settings

from intake import drafts
from intake.bot import Bot
from intake.models import DraftRevision, PendingPatch
from intake.tests import test_bot as helpers
from intake.tests.test_bot import CONFIG, GROUP, FakeLLM, msg


@override_settings(INTAKE=CONFIG)
class EditConversationTest(TestCase):
    setUp = helpers.BotTest.setUp

    def pending(self, changes=None, questions=None, **extra):
        return PendingPatch.objects.create(
            draft=self.draft, base_version=self.draft.version,
            changes=changes or [{'field': 'subtitle', 'new_value': '새 부제'}],
            questions=questions or [], message_id=888, **extra)

    def test_long_pending_text_is_available_and_preserved_on_followup(self):
        body = '첫째 원문 문단.\n\n' + ('원문을 줄이지 않습니다. ' * 400) + '\n\n마지막 문장.'
        old = self.pending([{'field': 'description', 'new_value': body}])
        llm = FakeLLM({'changes': [{'field': 'subtitle', 'new_value': '새 부제'}], 'questions': []})
        with mock.patch.object(llm, 'complete', wraps=llm.complete) as complete:
            new = drafts.propose_patch(self.draft, '부제도 고쳐줘', '운영진', llm)
        self.assertTrue(json.dumps(body, ensure_ascii=False) in complete.call_args.args[1])
        self.assertEqual({c['field']: c['new_value'] for c in new.changes},
                         {'description': body, 'subtitle': '새 부제'})
        old.refresh_from_db()
        self.assertEqual(old.status, PendingPatch.CANCELLED)
        draft, _ = drafts.apply_patch(new.id, '운영진')
        self.assertEqual(draft.book.description, body)

    def test_noop_does_not_cancel_changes_or_unanswered_question(self):
        old = self.pending(questions=['분류는 무엇인가요?'])
        drafts.propose_patch(self.draft, '잠깐', '운영진', FakeLLM({'changes': [], 'questions': []}))
        old.refresh_from_db()
        self.assertEqual(old.status, PendingPatch.PROPOSED)
        self.assertEqual(old.questions, ['분류는 무엇인가요?'])

    def test_invalid_category_keeps_previous_pending_and_book(self):
        old = self.pending()
        with self.assertRaises(drafts.PatchError):
            drafts.propose_patch(self.draft, '분류 바꿔줘', '운영진', FakeLLM({
                'changes': [{'field': 'category', 'new_value': '등록되지 않은 분류'}]}))
        old.refresh_from_db()
        self.assertEqual(old.status, PendingPatch.PROPOSED)
        self.draft.book.refresh_from_db()
        self.assertEqual(self.draft.book.subtitle, '삶과 생각')

    def test_explicit_apply_saves_once_without_publishing(self):
        old = self.pending()
        bot = Bot(self.tg, FakeLLM({}), config=CONFIG)
        update = msg(GROUP, '앞선 제안을 먼저 반영해 줘. 그러면 추가 제안할게.', reply_to=888)
        bot.handle_update(update)
        bot.handle_update(update)
        self.draft.refresh_from_db()
        self.draft.book.refresh_from_db()
        self.assertEqual(self.draft.book.subtitle, '새 부제')
        self.assertFalse(self.draft.book.is_published)
        self.assertEqual(self.draft.version, 2)
        self.assertEqual(DraftRevision.objects.filter(draft=self.draft).count(), 1)
        old.refresh_from_db()
        self.assertEqual(old.status, PendingPatch.APPLIED)

    def test_question_or_negation_is_not_apply(self):
        old = self.pending()
        for text in ['반영됐나요?', '아직 반영하지 마', '반영해 줘 라고 말하면 되나요?', '공개해 줘']:
            Bot(self.tg, FakeLLM({}), config=CONFIG).handle_update(msg(GROUP, text, reply_to=888))
        old.refresh_from_db()
        self.assertEqual(old.status, PendingPatch.PROPOSED)
        self.assertFalse(DraftRevision.objects.exists())

    def test_unanswered_question_cannot_be_applied(self):
        old = self.pending(questions=['분류를 확인해 주세요'])
        with self.assertRaises(drafts.PatchError):
            drafts.apply_patch(old.id, '운영진')
        self.assertFalse(DraftRevision.objects.exists())

    def test_reply_to_noop_response_keeps_book_context(self):
        bot = Bot(self.tg, FakeLLM({}), config=CONFIG)
        bot.handle_update(msg(GROUP, '어떻게 되어 있나요?', reply_to=777))
        reply_id = self.tg.next_id
        bot.llm = FakeLLM({'changes': [{'field': 'subtitle', 'new_value': '후속 수정'}]})
        bot.handle_update(msg(GROUP, '부제 수정', reply_to=reply_id, message_id=2))
        latest = PendingPatch.objects.filter(draft=self.draft).last()
        self.assertEqual(latest.changes, [{'field': 'subtitle', 'new_value': '후속 수정'}])

    def test_stale_parent_does_not_apply_newer_pending(self):
        old = self.pending(status=PendingPatch.CANCELLED)
        newer = PendingPatch.objects.create(
            draft=self.draft, base_version=1, message_id=889,
            changes=[{'field': 'subtitle', 'new_value': '다른 수정'}])
        Bot(self.tg, FakeLLM({}), config=CONFIG).handle_update(msg(GROUP, '반영해 줘', reply_to=old.message_id))
        newer.refresh_from_db()
        self.assertEqual(newer.status, PendingPatch.PROPOSED)
        self.assertFalse(DraftRevision.objects.exists())

    def test_reply_to_stale_apply_error_cannot_apply_another_pending_patch(self):
        old = self.pending(status=PendingPatch.CANCELLED)
        newer = PendingPatch.objects.create(draft=self.draft, base_version=1, message_id=889,
            changes=[{'field': 'full_price', 'new_value': 25000}])
        bot = Bot(self.tg, FakeLLM({}), config=CONFIG)
        bot.handle_update(msg(GROUP, '반영해 줘', reply_to=old.message_id))
        for message_id in (20, 21):
            bot.handle_update(msg(GROUP, '반영해 줘', reply_to=self.tg.next_id, message_id=message_id))
        newer.refresh_from_db()
        self.draft.book.refresh_from_db()
        self.assertEqual(newer.status, PendingPatch.PROPOSED)
        self.assertEqual(self.draft.book.full_price, 22000)
        self.assertFalse(DraftRevision.objects.exists())

    def test_new_edit_after_stale_apply_error_can_continue_current_pending(self):
        old = self.pending(status=PendingPatch.CANCELLED)
        PendingPatch.objects.create(draft=self.draft, base_version=1, message_id=889,
            changes=[{'field': 'full_price', 'new_value': 25000}])
        bot = Bot(self.tg, FakeLLM({}), config=CONFIG)
        bot.handle_update(msg(GROUP, '반영해 줘', reply_to=old.message_id))
        bot.llm = FakeLLM({'changes': [{'field': 'subtitle', 'new_value': '새 요청 부제'}]})
        bot.handle_update(msg(GROUP, '새 요청으로 부제를 바꿔줘', reply_to=self.tg.next_id, message_id=20))
        bot.handle_update(msg(GROUP, '반영해 줘', reply_to=self.tg.next_id, message_id=21))
        self.draft.book.refresh_from_db()
        self.assertEqual(self.draft.book.full_price, 25000)
        self.assertEqual(self.draft.book.subtitle, '새 요청 부제')
        self.assertEqual(DraftRevision.objects.count(), 1)

    def test_apply_completion_reply_accepts_a_new_edit(self):
        old = self.pending()
        bot = Bot(self.tg, FakeLLM({}), config=CONFIG)
        bot.handle_update(msg(GROUP, '반영해 줘', reply_to=old.message_id))
        bot.llm = FakeLLM({'changes': [{'field': 'full_price', 'new_value': 25000}]})
        bot.handle_update(msg(GROUP, '가격을 바꿔줘', reply_to=self.tg.next_id, message_id=20))
        bot.handle_update(msg(GROUP, '반영해 줘', reply_to=self.tg.next_id, message_id=21))
        self.draft.book.refresh_from_db()
        self.assertEqual(self.draft.book.full_price, 25000)
        self.assertEqual(DraftRevision.objects.count(), 2)

    def test_context_limit_fails_without_discarding_pending(self):
        old = self.pending([{'field': 'description', 'new_value': '긴 원문' * 14000}])
        with self.assertRaises(drafts.PatchError):
            drafts.propose_patch(self.draft, '추가해 줘', '운영진', FakeLLM({}))
        old.refresh_from_db()
        self.assertEqual(old.status, PendingPatch.PROPOSED)

    def test_append_keeps_exact_pending_body_and_new_source_passage(self):
        body = '첫 부분 원문.\n\n' + '긴 문단을 보존합니다. ' * 400
        self.pending([{'field': 'description', 'new_value': body}])
        addition = '■ 차례\n1부 농부의 하루\n2부 함께 살아가기'
        p = drafts.propose_patch(self.draft, '다음 부분도 추가해 줘\n' + addition, '운영진',
                                 FakeLLM({'append_description': addition, 'changes': [], 'questions': []}))
        draft, _ = drafts.apply_patch(p.pk, '운영진')
        self.assertEqual(draft.book.description, body.rstrip() + '\n\n' + addition)

    def test_append_rejects_invented_passage_and_keeps_pending(self):
        old = self.pending()
        with self.assertRaises(drafts.PatchError):
            drafts.propose_patch(self.draft, '차례 추가', '운영진',
                                 FakeLLM({'append_description': '자료에 없는 문장'}))
        old.refresh_from_db()
        self.assertEqual(old.status, PendingPatch.PROPOSED)

    def test_stale_proposed_parent_cannot_merge_an_unrelated_current_patch(self):
        old = self.pending()
        self.draft.version = 2
        self.draft.save()
        current = PendingPatch.objects.create(draft=self.draft, base_version=2,
            changes=[{'field': 'full_price', 'new_value': 25000}])
        with self.assertRaises(drafts.StaleError):
            drafts.propose_patch(self.draft, '부제를 다시 바꿔줘', '운영진',
                FakeLLM({'changes': [{'field': 'subtitle', 'new_value': '다시 수정'}]}), parent_patch=old)
        current.refresh_from_db()
        self.assertEqual(current.status, PendingPatch.PROPOSED)
        self.assertEqual(PendingPatch.objects.count(), 2)

    def test_cancelling_one_explicit_parent_preserves_another_pending(self):
        target = self.pending()
        other = PendingPatch.objects.create(draft=self.draft, base_version=1,
            changes=[{'field': 'full_price', 'new_value': 25000}])
        drafts.propose_patch(self.draft, '이 수정안은 취소', '운영진',
            FakeLLM({'cancel_previous': True}), parent_patch=target)
        target.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(target.status, PendingPatch.CANCELLED)
        self.assertEqual(other.status, PendingPatch.PROPOSED)

    def test_recent_source_tail_is_present_in_prompt(self):
        self.draft.source_text = '무지개를 변호하다\n' + '전체 원문 문장. ' * 3150 + '\n마지막 차례 항목'
        self.draft.files = {'source_revision': {'sha256': 'test'}}
        self.draft.save()
        llm = FakeLLM({})
        with mock.patch.object(llm, 'complete', wraps=llm.complete) as complete:
            drafts.propose_patch(self.draft, '전체 자료 반영', '운영진', llm)
        self.assertIn('마지막 차례 항목', complete.call_args.args[1])
