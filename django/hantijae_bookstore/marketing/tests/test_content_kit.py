from datetime import date
from django.test import TestCase

from marketing.kit import build_kit
from marketing.models import Draft
from marketing.tests.fakes import FakeLLM, make_book
from marketing.tests.test_content_supplements import CARDS, CROSS


class ContentKitTest(TestCase):
    def setUp(self):
        self.book = make_book(description='산에서 만난 사람들을 소개합니다. 흙과 노동의 시.')
        self.output = {'blog_title': '책 소개', 'blog_body': '공통 원고', 'blog_cards': CARDS, 'blog_cross': CROSS,
                       'instagram': '인스타 원고', 'instagram_cards': CARDS,
                       'recruit': {'body': '『나는 산속으로 더 깊이 들어간다』 서평단을 모십니다.\n'
                                   '[모집 인원]\n[신청 마감]\n[발표]\n[서평 올릴 곳]\n[서평 기간]\n'
                                   '이 글에 댓글로 읽고 싶은 이유를 한 줄 남겨 주세요.\n#한티재의책', 'cards': CARDS},
                       'editor_questions': ['원고를 처음 읽고 남은 장면은 무엇인가요?',
                                            '제목을 정하며 고민한 점이 있나요?', '독자와 나누고 싶은 이야기가 있나요?']}

    def build(self):
        return build_kit(self.book, FakeLLM(self.output), [], date(2026, 10, 14))

    def test_kit_persists_each_content_type_with_supplements(self):
        p = self.build()
        self.assertEqual(p.drafts.get(channel=Draft.BLOG).extra.get('cards'), CARDS)
        self.assertEqual(len(p.drafts.get(channel=Draft.BLOG).extra.get('cross', {}).get('hashtags', [])), 5)
        self.assertEqual(p.drafts.get(channel=Draft.INSTAGRAM).extra.get('cards'), CARDS)
        self.assertTrue(p.drafts.filter(channel='recruit').exists())
        self.assertTrue(p.drafts.filter(channel='editor').exists())
        questions = p.drafts.get(channel='editor')
        self.assertEqual(questions.extra, {'form': 'questions'})
        self.assertIn('여러 번 나눠 답장', questions.body)
        self.assertNotIn('저는', questions.body)

    def test_recruit_unapproved_counts_and_deadlines_become_literal_placeholders(self):
        self.output['recruit']['body'] = '30명을 모십니다. 신청 마감은 10월 20일입니다.'
        p = self.build()
        d = p.drafts.get(channel='recruit')
        for placeholder in ('[모집 인원]', '[신청 마감]', '[발표]', '[서평 올릴 곳]', '[서평 기간]'):
            self.assertIn(placeholder, d.body)
        self.assertNotIn('30명', d.body)
        self.assertNotIn('20일', d.body)
        self.assertIn('댓글로 읽고 싶은 이유', d.body)

    def test_recruit_cannot_reuse_page_count_as_approved_recruitment_count(self):
        self.output['recruit']['body'] += '\n모집 인원은 132명입니다.\n선정된 분께 선물을 보내 드립니다.'
        d = self.build().drafts.get(channel='recruit')
        self.assertNotIn('132명', d.body)
        self.assertNotIn('선물', d.body)
        self.assertIn('[모집 인원]', d.body)

    def test_single_question_or_malformed_question_payload_is_not_a_post(self):
        for questions in (['하나인가요?'], '질문처럼 보이는 산문', [None, {}, '하나인가요?']):
            self.output['editor_questions'] = questions
            self.assertFalse(self.build().drafts.filter(channel='editor').exists())

    def test_invalid_supplements_leave_copyable_kit_body(self):
        self.output['blog_cards'] = [{'show': '표지', 'text': '999권'}] * 3
        p = self.build()
        self.assertEqual(p.drafts.get(channel=Draft.BLOG).body, '공통 원고')
        self.assertNotIn('cards', p.drafts.get(channel=Draft.BLOG).extra)
