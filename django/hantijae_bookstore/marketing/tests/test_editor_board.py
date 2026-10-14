from datetime import date

from django.test import TestCase

from marketing import board, notion_sync as ns
from marketing.messages import OPEN, POSTED, SKIPPED
from marketing.models import Draft, Proposal


class EditorBoardTest(TestCase):
    def setUp(self):
        self.p = Proposal.objects.create(kind=Proposal.NOW, headline='편집 일기')
        self.q = Draft.objects.create(proposal=self.p, channel='editor', body='질문', extra={'form': 'questions'})
        self.target = ns.now_target([self.p], '허브', date(2026, 10, 16))

    def test_question_never_counts_as_posted_even_if_status_was_set(self):
        self.p.status = Proposal.ACTED
        self.p.save()
        self.q.status = Draft.POSTED
        self.q.save()
        self.assertEqual(board.item_state(self.p), OPEN)
        self.assertEqual(board.channel_state(self.p, 'editor'), OPEN)

    def test_only_question_has_no_notion_progress_count(self):
        self.assertEqual(ns._progress_states(self.target, [OPEN]), [])

    def test_generated_post_counts_and_older_question_cannot_override_it(self):
        Draft.objects.create(proposal=self.p, channel='editor', body='게시글', version=2,
                             extra={'form': 'post'}, status=Draft.POSTED, parent=self.q)
        Draft.objects.create(proposal=self.p, channel='editor', body='추가 질문', version=3,
                             extra={'form': 'questions'}, status=Draft.SKIPPED)
        self.assertEqual(board.item_state(self.p), POSTED)
        self.assertEqual(ns._progress_states(self.target, [POSTED]), [POSTED])

    def test_latest_question_does_not_override_post_skip(self):
        Draft.objects.create(proposal=self.p, channel='editor', body='글', version=2,
                             extra={'form': 'post'}, status=Draft.SKIPPED, parent=self.q)
        Draft.objects.create(proposal=self.p, channel='editor', body='질문', version=3, extra={'form': 'questions'})
        self.assertEqual(board.channel_state(self.p, 'editor'), SKIPPED)

    def test_kit_questions_are_excluded_while_other_channels_count(self):
        self.p.kind = Proposal.KIT
        self.p.save()
        Draft.objects.create(proposal=self.p, channel=Draft.BLOG, body='글')
        target = ns.Target(ns.KIT, [self.p], [(self.p, 'editor', '질문'), (self.p, Draft.BLOG, '글')],
                           '자료', date(2026, 10, 16), '허브')
        self.assertEqual(ns._progress_states(target, [OPEN, OPEN]), [OPEN])
