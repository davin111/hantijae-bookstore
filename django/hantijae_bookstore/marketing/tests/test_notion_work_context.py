from unittest import mock
from datetime import timedelta

from django.test import TestCase

from context.models import ContextEntry
from marketing import moments as M
from marketing.tests.fakes import FakeLLM, make_book
from marketing.tests.test_moments import NOW, entry, moment, new_item


class WorkContextTest(TestCase):
    def setUp(self):
        self.book = make_book()
        self.work = ContextEntry.objects.create(
            key='notion-work:tasks:t1', source='notion', at=NOW,
            heading=f'『{self.book.title}』 · 할 일',
            text=f'관련 책: 『{self.book.title}』\n마감일: 2026-10-02\n내용: 원고 검토')

    def test_internal_work_is_context_for_related_book_not_new_alert_input(self):
        e = entry(1, f'『{self.book.title}』 금요일 저자 강연')
        self.assertNotIn(self.work, M.pending_entries())
        self.assertIn(self.work, M.context_before([e], NOW))
        self.assertNotIn(self.work, M.context_before([entry(2, '다른 책 이야기')], NOW))
        self.assertIn('내부 업무 참고', M.line(self.work))

    def test_model_cannot_use_only_internal_deadline_as_public_evidence(self):
        e = entry(1, f'『{self.book.title}』 검토 중')
        actions, _ = M.validate({'new': [new_item([self.work.id])]},
                                {self.work.id: self.work, e.id: e}, {}, M.book_index(), NOW.date())
        self.assertEqual(actions, [])

    def test_completion_forgotten_and_expired_context_are_not_reused(self):
        e = entry(1, self.book.title)
        self.assertNotIn(self.work, M.context_before([e], NOW + timedelta(days=3)))
        ContextEntry.objects.filter(pk=self.work.pk).update(text='')
        self.assertNotIn(self.work, M.context_before([e], NOW))

    def test_mixed_internal_evidence_is_rejected_for_new_and_update(self):
        e = entry(1, f'『{self.book.title}』 금요일 저자 강연')
        s = moment(book=self.book)
        raw = {'new': [new_item([e.id, self.work.id])],
               'updates': [{'id': s.id, 'evidence': [e.id, self.work.id], 'status': 'cancelled'}]}
        actions, _ = M.validate(raw, {e.id: e, self.work.id: self.work}, {s.id: s}, M.book_index(), NOW.date())
        self.assertEqual(actions, [])

    def test_internal_deadline_not_cited_cannot_be_kept_as_unverified_date(self):
        e = entry(1, f'『{self.book.title}』 검토 중')
        s = moment(book=self.book)
        date_text = '10월 2일 계약 협의'
        raw = {'new': [new_item([e.id], date_text=date_text)],
               'updates': [{'id': s.id, 'evidence': [e.id], 'date': '2026-10-02', 'date_text': date_text}]}
        actions, _ = M.validate(raw, {e.id: e, self.work.id: self.work}, {s.id: s}, M.book_index(), NOW.date())
        self.assertEqual(actions, [])
        # 공개 근거에 일정이 있는 정상 후보는 업무 참고가 함께 있어도 유지한다.
        e.text = f'『{self.book.title}』 10월 2일 저자 강연'
        actions, _ = M.validate({'new': [new_item([e.id], date_text='10월 2일')]},
                                {e.id: e, self.work.id: self.work}, {}, M.book_index(), NOW.date())
        self.assertEqual(len(actions), 1)
        ContextEntry.objects.filter(pk=self.work.pk).update(text='내용', forgotten=True)
        self.assertNotIn(self.work, M.context_before([e], NOW))

    def test_daily_enables_related_collection(self):
        from types import SimpleNamespace
        with self.settings(INTAKE={'NOTION_DATA_SOURCE_ID': 'catalog'}), \
                mock.patch.object(M.context_notion, 'sync', return_value=2) as sync, \
                mock.patch.object(M.context_links, 'read_links', return_value=0):
            deps = SimpleNamespace(notion=object(), llm=FakeLLM({'new': []}))
            M.daily(deps, NOW, photos=False)
        sync.assert_called_once_with(deps.notion, 'catalog', NOW, related=True)

    def test_daily_really_collects_work_without_creating_moments_or_calling_llm(self):
        from types import SimpleNamespace
        from context.tests.test_notion_work import Client, NOW as work_now
        from marketing.models import Signal
        ContextEntry.objects.all().delete()
        llm = mock.Mock()
        with self.settings(INTAKE={'NOTION_DATA_SOURCE_ID': 'catalog'}), \
                mock.patch.object(M.context_notion, 'PAUSE', 0):
            deps = SimpleNamespace(notion=Client(), llm=llm)
            first = M.daily(deps, work_now, photos=False)
            second = M.daily(deps, work_now, photos=False)
        self.assertEqual((first.notion, second.notion), (2, 0))
        self.assertFalse(first.errors or second.errors)
        self.assertEqual(ContextEntry.objects.exclude(text='').count(), 2)
        self.assertFalse(Signal.objects.exists())
        self.assertFalse(llm.mock_calls)

    def test_relative_internal_deadlines_require_public_support(self):
        e = entry(1, f'『{self.book.title}』 검토 중')
        for phrase in ('내일', '다음 주 금요일', '다음 주말'):
            with self.subTest(phrase=phrase):
                actions, _ = M.validate({'new': [new_item([e.id], date_='', date_text=phrase)]},
                                        {e.id: e, self.work.id: self.work}, {}, M.book_index(), NOW.date())
                self.assertEqual(actions, [])
