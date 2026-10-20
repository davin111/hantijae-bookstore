from copy import deepcopy
from datetime import date

from django.test import TestCase

from marketing.briefing import compose
from marketing.candidates import Candidate
from marketing.tests.fakes import FakeLLM, make_book
from marketing.models import Draft, Proposal
from marketing.supplements import rewrite_extra


class PublicCopyTest(TestCase):
    def setUp(self):
        self.book = make_book(description='<p>밥을 짓는 사람의 노동을 따라갑니다.</p>',
                              short_description='밥과 노동에 관한 에세이')
        self.candidate = Candidate(id='loan:test', kind='loan', books=[self.book],
                                   summary='9월 도서관 대출 59회, 평균 26회',
                                   facts={'loans': 59, 'avg': 26}, urgency=1)
        self.raw = {'candidate_id': 'loan:test', 'headline': '다시 읽는 책',
                    'reason': '9월 도서관 대출 59회여서 다시 소개합니다.',
                    'draft': {'channel': 'instagram', 'title': '', 'body': '밥을 짓는 사람의 노동을 따라갑니다.',
                              'cards': [{'show': '글 카드', 'text': '밥과 노동에 관한 에세이'}] * 3,
                              'cross': {'lead': '밥과 노동에 관한 에세이', 'hashtags': ['#한티재의책']}}}

    def compose(self, raw):
        return compose(FakeLLM({'items': [raw]}), [self.candidate], date(2026, 10, 20))

    def test_loan_candidate_supplies_book_content_separately_from_selection_metrics(self):
        data = self.candidate.as_prompt()
        self.assertIn('밥을 짓는 사람의 노동을 따라갑니다.', str(data.get('book_content', '')))
        self.assertNotIn('<p>', str(data.get('book_content', '')))
        self.assertEqual(data['facts']['loans'], 59)

    def test_internal_reason_keeps_counts_but_public_body_and_title_reject_them(self):
        for field in ('body', 'title'):
            for text in ('9월 도서관 대출 59회', '앞선 11달 평균 26회', '판매 지수 1234'):
                raw = deepcopy(self.raw)
                raw['draft'][field] = text
                with self.subTest(field=field, text=text):
                    items, dropped = self.compose(raw)
                    self.assertFalse(items)
                    self.assertTrue(dropped)
        items, dropped = self.compose(self.raw)
        self.assertFalse(dropped)
        self.assertIn('59회', items[0][2])

    def test_statistics_cannot_leak_through_cards_or_cross_posting_lead(self):
        raw = deepcopy(self.raw)
        raw['draft']['cards'][0] = {'show': '글 카드', 'text': '대출 59회 · 평균 26회'}
        raw['draft']['cross']['lead'] = '9월 도서관 대출 59회'
        items, _ = self.compose(raw)
        self.assertEqual(len(items), 1)
        extra = items[0][3]['extra']
        self.assertNotIn('59회', str(extra))

    def test_event_and_funding_numbers_are_not_operational_statistics(self):
        self.candidate.kind = 'fund'
        self.candidate.facts = {'date': '2026-10-23', 'supporters': 350}
        raw = deepcopy(self.raw)
        raw['draft']['body'] = '10월 23일 만나요. 북펀드에 350분이 함께했습니다.'
        items, dropped = self.compose(raw)
        self.assertEqual(len(items), 1)
        self.assertFalse(dropped)

    def test_sales_surge_counts_are_only_selection_evidence(self):
        self.candidate.kind = 'surge'
        self.candidate.summary = '최근 7일 59권 팔렸음(평소 주 26권)'
        raw = deepcopy(self.raw)
        raw['draft']['body'] = '최근 7일 59권 팔렸습니다. 평소 주 26권보다 더 많은 독자에게 갔습니다.'
        self.assertFalse(self.compose(raw)[0])

    def test_rewrite_cannot_keep_old_statistical_cards_as_fallback(self):
        p = Proposal.objects.create(book=self.book, kind='brief_item', headline='책 소개')
        d = Draft.objects.create(proposal=p, channel='instagram', body='책 소개', extra={
            'cards': [{'show': '글 카드', 'text': '대출 59회'}] * 3,
            'cross': {'lead': '9월 도서관 대출 59회', 'hashtags': ['#한티재의책']}})
        extra = rewrite_extra(d, {}, source_text=self.book.description)
        self.assertNotIn('59회', str(extra))

    def test_rewrite_reply_with_statistics_never_creates_a_public_draft(self):
        from marketing.bot import Marketing
        from marketing.tests.fakes import FakeTG
        from marketing.tests.test_bot import FakeHost
        p = Proposal.objects.create(book=self.book, kind='brief_item', headline='책 소개')
        Draft.objects.create(proposal=p, channel='instagram', body='원래 원고', chat_id=-200, message_id=50)
        tg = FakeTG()
        Marketing(tg, FakeLLM({'title': '', 'body': '도서관 대출 59회', 'note': ''}), FakeHost()).handle_reply(
            -200, 50, {'message_id': 51}, '책 내용으로 고쳐 주세요', '운영진')
        self.assertEqual(Draft.objects.count(), 1)
        self.assertFalse(any('59회' in c['text'] for c in tg.sent('send')))

    def test_paraphrased_counts_are_not_public_book_material(self):
        for text in ('9월에는 59번 빌려 읽혔습니다.', '59회 · 월평균 26회', '평소보다 많은 59명이 읽었습니다.'):
            raw = deepcopy(self.raw)
            raw['draft']['body'] = text
            with self.subTest(text=text):
                self.assertFalse(self.compose(raw)[0])
            raw = deepcopy(self.raw)
            raw['draft']['cards'][0] = {'show': '글 카드', 'text': text}
            items, _ = self.compose(raw)
            self.assertNotIn('59', str(items[0][3]['extra']))

    def test_empty_rewrite_does_not_restore_statistical_original_body(self):
        from marketing.bot import Marketing
        from marketing.tests.fakes import FakeTG
        from marketing.tests.test_bot import FakeHost
        p = Proposal.objects.create(book=self.book, kind='brief_item', headline='책 소개')
        Draft.objects.create(proposal=p, channel='instagram', body='도서관 대출 59회', chat_id=-200, message_id=50)
        tg = FakeTG()
        Marketing(tg, FakeLLM({'title': '', 'body': '', 'note': ''}), FakeHost()).handle_reply(
            -200, 50, {'message_id': 51}, '책 내용으로 고쳐 주세요', '운영진')
        self.assertEqual(Draft.objects.count(), 1)
        self.assertFalse(any('59회' in c['text'] for c in tg.sent('send')))

    def test_loan_rewrite_cannot_relabel_counts_as_readers(self):
        from marketing.bot import Marketing
        from marketing.tests.fakes import FakeTG
        from marketing.tests.test_bot import FakeHost
        p = Proposal.objects.create(book=self.book, kind='brief_item', headline='책 소개', candidate_key='loan:test')
        Draft.objects.create(proposal=p, channel='instagram', body='원래 원고', chat_id=-200, message_id=50)
        Marketing(FakeTG(), FakeLLM({'title': '', 'body': '59명이 읽은 책입니다.'}), FakeHost()).handle_reply(
            -200, 50, {'message_id': 51}, '책 내용으로 고쳐 주세요', '운영진')
        self.assertEqual(Draft.objects.count(), 1)

    def test_loan_rewrite_removes_legacy_counts_without_explicit_metric_words(self):
        p = Proposal.objects.create(book=self.book, kind='brief_item', headline='책 소개', candidate_key='loan:test')
        d = Draft.objects.create(proposal=p, channel='instagram', body='책 소개', extra={
            'cards': [{'show': '글 카드', 'text': '59명이 읽은 책입니다.'}] * 3,
            'cross': {'lead': '59명이 읽은 책입니다.', 'hashtags': ['#한티재의책']}})
        self.assertNotIn('59', str(rewrite_extra(d, {}, source_text=self.book.description)))
