from datetime import date, datetime

from django.test import TestCase

from intake.models import WorkerState
from marketing import notion_sync as ns
from marketing.bot import Marketing
from marketing.models import Draft, DraftMessage, Proposal
from marketing.tests.fakes import FakeLLM, FakeNotion, FakeTG
from marketing.tests.test_bot import FakeHost, GROUP, cbq
from marketing.timeutil import KST


NOW = datetime(2026, 10, 16, 10, tzinfo=KST)


class EditorCallbackTest(TestCase):
    def setUp(self):
        self.p = Proposal.objects.create(kind=Proposal.NOW, headline='편집 일기')
        self.q = Draft.objects.create(proposal=self.p, channel=Draft.EDITOR, body='질문', extra={'form': 'questions'})
        self.a = self.post('A', 2)
        self.host, self.tg = FakeHost(), FakeTG()
        self.m = Marketing(self.tg, FakeLLM({}), self.host)

    def post(self, author, version, parent=None, question_id=None):
        return Draft.objects.create(proposal=self.p, channel=Draft.EDITOR, body=f'{author} 글',
                                    version=version, parent=parent or self.q,
                                    extra={'form': 'post', 'author': author,
                                           'question_id': question_id or self.q.pk})

    def notion_edit_a_after_b(self):
        WorkerState.put(ns.SWITCH, 'on')
        WorkerState.put(ns.DS, 'ds1')
        self.host.notion = FakeNotion()
        ns.ensure_page(self.host.notion, ns.now_target([self.p], '편집 일기', date(2026, 10, 16)), NOW)
        self.a.refresh_from_db()
        b = self.post('B', 3)
        ns.append_version(self.host.notion, b)
        self.host.notion.edit(self.host.notion.kids[self.a.notion['box']][0], '노션에서 고친 A 글')
        return b

    def test_old_a_posted_button_marks_latest_a_and_leaves_newer_b_unposted(self):
        self.post('B', 3)
        latest_a = self.post('A', 4, parent=self.a)
        latest_b = self.post('B', 5)
        self.m.handle_callback(f'mk:p:{self.a.pk}', GROUP, cbq(), '검수자')
        latest_a.refresh_from_db()
        latest_b.refresh_from_db()
        self.a.refresh_from_db()
        self.assertEqual(latest_a.status, Draft.POSTED)
        self.assertEqual((latest_b.status, self.a.status), (Draft.DRAFT, Draft.DRAFT))

    def test_posted_button_preserves_a_notion_edit_and_global_version_order(self):
        b = self.notion_edit_a_after_b()
        self.m.handle_callback(f'mk:p:{self.a.pk}', GROUP, cbq(), '검수자')
        posted = Draft.objects.get(status=Draft.POSTED)
        b.refresh_from_db()
        self.assertEqual((posted.extra['author'], posted.body, posted.parent_id),
                         ('A', '노션에서 고친 A 글', self.a.pk))
        self.assertEqual((posted.version, posted.origin, b.status), (4, Draft.NOTION, Draft.DRAFT))
        self.m.handle_callback(f'mk:p:{self.a.pk}', GROUP, cbq(), '검수자')
        self.assertEqual(Draft.objects.filter(status=Draft.POSTED).count(), 1)
        self.assertEqual(Draft.objects.count(), 4)  # 같은 Notion 내용을 새 판으로 중복 저장하지 않음

    def test_a_reply_rewrites_a_notion_edit_without_loading_b(self):
        b = self.notion_edit_a_after_b()
        DraftMessage.objects.create(draft=self.a, chat_id=GROUP, message_id=801)
        self.m.llm = FakeLLM({'title': '', 'body': '노션에서 고친 A 글. 끝맺음.', 'note': ''})
        self.m.handle_reply(GROUP, 801, {'message_id': 802}, '끝맺음을 더해 주세요.', '검수자')
        rewritten = self.p.drafts.order_by('-version', '-id').first()
        self.assertEqual((rewritten.extra['author'], rewritten.version), ('A', 5))
        self.assertEqual((rewritten.parent.origin, rewritten.parent.body), (Draft.NOTION, '노션에서 고친 A 글'))
        b.refresh_from_db()
        self.assertEqual(b.body, 'B 글')

    def test_same_author_different_question_does_not_replace_clicked_post(self):
        other_q = Draft.objects.create(proposal=self.p, channel=Draft.EDITOR, body='다른 질문', version=3,
                                        extra={'form': 'questions'})
        other_a = self.post('A', 4, parent=other_q, question_id=other_q.pk)
        self.m.handle_callback(f'mk:p:{self.a.pk}', GROUP, cbq(), '검수자')
        self.a.refresh_from_db()
        other_a.refresh_from_db()
        self.assertEqual((self.a.status, other_a.status), (Draft.POSTED, Draft.DRAFT))

    def test_unidentified_author_keeps_clicked_post_separate(self):
        unknown = self.post('', 3)
        other_unknown = self.post('', 4)
        self.m.handle_callback(f'mk:p:{unknown.pk}', GROUP, cbq(), '검수자')
        unknown.refresh_from_db()
        other_unknown.refresh_from_db()
        self.assertEqual((unknown.status, other_unknown.status), (Draft.POSTED, Draft.DRAFT))

    def test_skip_a_versions_does_not_skip_b_or_change_posted_a(self):
        self.a.status = Draft.POSTED
        self.a.save()
        b = self.post('B', 3)
        a_revision = self.post('A', 4, parent=self.a)
        newer_b = self.post('B', 5, parent=b)
        self.m.handle_callback(f'mk:l:{a_revision.pk}', GROUP, cbq(), '검수자')
        for row in (self.a, b, a_revision, newer_b):
            row.refresh_from_db()
        self.assertEqual((self.a.status, a_revision.status), (Draft.POSTED, Draft.SKIPPED))
        self.assertEqual((b.status, newer_b.status), (Draft.DRAFT, Draft.DRAFT))

    def test_skip_unknown_revision_follows_ancestors_without_other_unknown_author(self):
        unknown = self.post('', 3)
        revision = self.post('', 4, parent=unknown)
        other = self.post('', 5)
        self.m.handle_callback(f'mk:l:{revision.pk}', GROUP, cbq(), '검수자')
        for row in (unknown, revision, other):
            row.refresh_from_db()
        self.assertEqual((unknown.status, revision.status, other.status),
                         (Draft.SKIPPED, Draft.SKIPPED, Draft.DRAFT))

    def test_skip_original_question_retains_existing_channel_skip(self):
        copy = Draft.objects.create(proposal=self.p, channel=Draft.EDITOR, body='고친 질문', version=3,
                                    parent=self.q, extra={'form': 'questions'})
        self.m.handle_callback(f'mk:l:{self.q.pk}', GROUP, cbq(), '검수자')
        self.q.refresh_from_db()
        copy.refresh_from_db()
        self.assertEqual((self.q.status, copy.status), (Draft.SKIPPED, Draft.SKIPPED))
