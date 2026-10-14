from copy import deepcopy
from datetime import date
from types import SimpleNamespace

from django.test import TestCase

from marketing.briefing import compose, save_briefing
from marketing.candidates import Candidate
from marketing import messages, notion_blocks
from marketing.models import Draft, Proposal
from marketing.tests.fakes import FakeLLM, make_book


CARDS = [{'show': '책 표지 준비', 'text': '산에서 만난 사람들'},
         {'show': '책 펼친 면 준비', 'text': '흙과 노동의 시'},
         {'show': '책 제목과 지은이', 'text': '함께 읽어요'}]
CROSS = {'lead': '산에서 만난 사람들을 소개합니다.',
         'hashtags': ['#시', '#산', '#책', '#독서', '#출판', '#한티재의책']}
TODAY = date(2026, 10, 14)


class SupplementStorageTest(TestCase):
    def setUp(self):
        self.book = make_book(description='산에서 만난 사람들을 소개합니다. 흙과 노동의 시. 132쪽.')
        self.cand = Candidate(id='blog:test', kind='blog', books=[self.book], summary='소개', facts={}, urgency=1)

    def compose(self, cards=CARDS, cross=CROSS, **kwargs):
        draft = {'channel': 'blog', 'title': '책 소개', 'body': '정상 본문',
                 'cards': deepcopy(cards), 'cross': deepcopy(cross), **kwargs}
        return compose(FakeLLM({'items': [{'candidate_id': self.cand.id, 'headline': '책 소개',
                                         'reason': '지금 함께 읽어요', 'draft': draft}]}), [self.cand], TODAY)

    def test_compose_and_save_keep_valid_supplements(self):
        items, dropped = self.compose()
        self.assertEqual(dropped, [])
        draft = save_briefing(items, TODAY).items.get().drafts.get()
        self.assertEqual(draft.extra.get('cards'), CARDS)
        self.assertEqual(draft.extra.get('cross', {}).get('hashtags'), ['#한티재의책', '#시', '#산', '#책', '#독서'])
        self.assertEqual(draft.body, '정상 본문')

    def test_invalid_card_numbers_or_quotes_do_not_drop_body(self):
        for bad in ('999권 판매', '30명이 읽었습니다', '“원문에 없는 인용입니다”'):
            with self.subTest(bad=bad):
                cards = deepcopy(CARDS)
                cards[0]['text'] = bad
                items, dropped = self.compose(cards=cards)
                self.assertEqual((len(items), dropped), (1, []))
                self.assertNotIn('cards', items[0][3].get('extra', {}))

    def test_invalid_shapes_counts_and_overlong_quotes_are_not_truncated(self):
        long_quote = '“' + '가' * 41 + '”'
        self.book.description = long_quote
        cases = [None, '카드', {}, CARDS[:2], CARDS * 2 + CARDS[:1],
                 [{'show': '가' * 61, 'text': '글'}] + CARDS[1:],
                 [{'show': '내지 준비', 'text': long_quote}] + CARDS[1:]]
        for cards in cases:
            with self.subTest(cards=cards):
                items, _ = self.compose(cards=cards)
                self.assertEqual(items[0][3]['body'], '정상 본문')
                self.assertNotIn('cards', items[0][3].get('extra', {}))

    def test_memorial_supplements_cannot_add_sales_or_profile_promises(self):
        self.cand.memorial = True
        cards = deepcopy(CARDS)
        cards[0]['text'] = '지금 구매하세요'
        items, _ = self.compose(cards=cards, cross={'lead': '프로필 링크에서 구매하세요', 'hashtags': ['#구매']})
        self.assertEqual(len(items), 1)
        extra = items[0][3].get('extra', {})
        self.assertNotIn('cards', extra)
        self.assertNotIn('구매', str(extra))

    def test_letter_keeps_places_and_ignores_supplements(self):
        items, _ = self.compose(channel='letter', to=['독서 모임'])
        draft = save_briefing(items, TODAY).items.get().drafts.get()
        self.assertEqual(draft.extra, {'places': ['독서 모임']})


class SupplementPresentationTest(TestCase):
    def draft(self, body='본문', title='제목', extra=None):
        return SimpleNamespace(id=7, channel='blog', title=title, body=body,
                               extra=extra if extra is not None else {'cards': CARDS, 'cross': CROSS},
                               label='네이버 블로그 글')

    def test_memo_is_separate_from_copyable_body_and_notion_edit_box(self):
        d = self.draft()
        text = messages.supplement_text(d)
        self.assertIn('카드 구성안 (3장)', text)
        self.assertIn('책 표지 준비', text)
        self.assertNotIn('첫 두 줄만', text)
        self.assertNotIn('프로필 링크에서 서점으로', text)
        self.assertEqual(messages.draft_text(d), '제목\n\n본문')
        self.assertIn('카드 구성안', notion_blocks.kit_memo(d))
        self.assertIn('카드 구성안', notion_blocks.item_memo(SimpleNamespace(reason='이유', extra={}), d))
        self.assertEqual(notion_blocks.box_content(d.title, d.body)[1]['paragraph']['rich_text'][0]['text']['content'], '본문')

    def test_final_title_body_newlines_and_hashtags_define_length_boundary(self):
        # title 1 + two newlines + body 2189 + two newlines + tag 6 = 2200.
        for size, long in ((2188, False), (2189, False), (2190, True)):
            d = self.draft(title='책', body='가' * size, extra={'cross': {'lead': '', 'hashtags': ['#한티재의책']}})
            text = messages.supplement_text(d)
            self.assertEqual('짧은본' in text, long)
            self.assertNotIn('0문단', text)

    def test_long_guidance_keeps_essential_event_information_in_original(self):
        body = '가' * 2201 + '\n\n10월 16일 대구서점. 신청은 댓글로 남겨 주세요.'
        d = self.draft(body=body)
        self.assertIn('짧은본', messages.supplement_text(d))
        self.assertIn('10월 16일 대구서점', messages.draft_text(d))

    def test_questions_offer_only_defer_and_kit_has_direct_buttons(self):
        d = self.draft(extra={'form': 'questions'})
        d.channel = 'editor'
        labels = [b['text'] for row in messages.draft_buttons(d)['inline_keyboard'] for b in row]
        self.assertEqual(labels, ['다음에'])
        recruit = self.draft()
        recruit.channel = 'recruit'
        labels = [b['text'] for row in messages.kit_buttons(SimpleNamespace(id=2), [recruit, d])['inline_keyboard'] for b in row]
        self.assertIn('서평단 글 보기', labels)
        self.assertIn('편집 후기 질문', labels)


class SupplementRewriteTest(TestCase):
    def test_rewrite_preserves_other_extra_and_validates_replacements(self):
        from marketing.supplements import rewrite_extra
        d = SimpleNamespace(channel=Draft.BLOG, extra={'cards': CARDS, 'cross': {'lead': '원래 도입', 'hashtags': ['#한티재의책']},
                                   'form': 'post', 'answers': [{'text': '기록'}]})
        result = rewrite_extra(d, {'cards': [{'show': '거짓', 'text': '999권'}]}, source_text='자료')
        self.assertEqual(result, d.extra)
        replacement = deepcopy(CARDS)
        replacement[0]['text'] = '고친 문구'
        result = rewrite_extra(d, {'cards': replacement}, note='고친 문구로 써 주세요', source_text='자료')
        self.assertEqual(result['cards'][0]['text'], '고친 문구')
        self.assertEqual(result['answers'], [{'text': '기록'}])
        self.assertEqual(d.extra['cards'][0]['text'], '산에서 만난 사람들')
