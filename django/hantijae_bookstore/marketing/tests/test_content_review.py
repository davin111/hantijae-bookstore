from copy import deepcopy
from datetime import date
from types import SimpleNamespace

from django.test import TestCase

from marketing import board, messages, notion_sync
from marketing.kit import build_kit
from marketing.models import Draft, Proposal
from marketing.supplements import normalize_extra, rewrite_extra
from marketing.tests.fakes import FakeLLM, make_book
from marketing.tests.test_content_supplements import CARDS


class RecruitmentCardReviewTest(TestCase):
    def test_recruitment_invitation_is_shown_once_when_model_already_includes_it(self):
        from marketing.kit import RECRUIT_FIELDS, _recruit_body
        book = make_book()
        cta = '이 글에 댓글로 읽고 싶은 이유를 한 줄 남겨 주세요.'
        raw = '\n'.join(['책 이야기입니다.', cta, *RECRUIT_FIELDS])
        body = _recruit_body(raw, book, ['책 이야기입니다.'])
        self.assertEqual(body.count(cta), 1)

    def test_book_page_count_is_not_an_approved_recruitment_condition(self):
        book = make_book(page_count=132)
        output = {'recruit': {'body': '서평단을 모십니다', 'cards': [
            {'show': '책 표지', 'text': '132명 모집'},
            {'show': '모집 안내', 'text': '선정된 분께 선물을 드립니다'},
            {'show': '신청 안내', 'text': '지금 신청하세요'}]}}
        draft = build_kit(book, FakeLLM(output), [], date(2026, 10, 14)).drafts.get(channel=Draft.RECRUIT)
        cards = draft.extra.get('cards') or []
        self.assertEqual(len(cards), 3)
        text = messages.supplement_text(draft)
        self.assertNotIn('132명', text)
        self.assertNotIn('선물', text)
        for field in ('[모집 인원]', '[신청 마감]', '[발표]', '[서평 올릴 곳]', '[서평 기간]'):
            self.assertIn(field, text)
        self.assertIn('댓글', text)
        self.assertTrue(all(len(c['show']) <= 60 and len(c['text']) <= 40 for c in cards))

    def test_recruit_rewrite_cannot_restore_invented_conditions_from_a_book_number(self):
        draft = SimpleNamespace(channel=Draft.RECRUIT, extra={})
        output = {'cards': [{'show': '책 표지', 'text': '132명 모집'}] * 3}
        extra = rewrite_extra(draft, output, source_text='책은 132쪽입니다.')
        self.assertEqual(len(extra.get('cards', [])), 3)
        self.assertNotIn('132명', str(extra))
        self.assertIn('[모집 인원]', str(extra))


class SupplementChannelReviewTest(TestCase):
    def test_rewrite_does_not_add_supplements_to_non_public_copy_channels(self):
        output = {'cards': CARDS, 'cross': {'lead': '도입', 'hashtags': ['#한티재의책']}}
        for channel, form in ((Draft.LETTER, ''), (Draft.LINKS, ''), (Draft.SHORT, ''),
                              (Draft.EDITOR, 'questions'), (Draft.EDITOR, 'post')):
            with self.subTest(channel=channel, form=form):
                extra = {'form': form, 'to': '받는 곳'}
                draft = SimpleNamespace(channel=channel, extra=deepcopy(extra))
                self.assertEqual(rewrite_extra(draft, output), extra)

    def test_rewrite_still_accepts_cards_for_blog_instagram_and_recruit(self):
        for channel in (Draft.BLOG, Draft.INSTAGRAM, Draft.RECRUIT):
            with self.subTest(channel=channel):
                draft = SimpleNamespace(channel=channel, extra={})
                self.assertEqual(rewrite_extra(draft, {'cards': CARDS})['cards'], CARDS)

    def test_validated_numeric_hashtag_is_displayed_and_counted_for_length(self):
        extra = normalize_extra({'cross': {'hashtags': ['#10월', '#한티재의책']}}, ['10월'])
        self.assertEqual(extra['cross']['hashtags'], ['#한티재의책', '#10월'])
        # 1-char title + 2 newlines + 2185-char body + 2 newlines + 11-char tags = 2201.
        draft = SimpleNamespace(channel=Draft.BLOG, title='책', body='가' * 2185, extra=extra)
        text = messages.supplement_text(draft)
        self.assertIn('#10월', text)
        self.assertIn('2,201자', text)
        self.assertIn('짧은본', text)


class QuestionHubReviewTest(TestCase):
    def setUp(self):
        self.p = Proposal.objects.create(kind=Proposal.KIT, headline='홍보 자료', chat_id=-200, message_id=800)
        self.q = Draft.objects.create(proposal=self.p, channel=Draft.EDITOR, body='질문',
                                      extra={'form': 'questions'}, status=Draft.SKIPPED)

    def labels(self):
        return [b['text'] for row in board.hub_of(self.p).buttons['inline_keyboard'] for b in row]

    def test_skipped_question_remains_skipped_but_never_counts_as_a_post(self):
        self.assertEqual(board.channel_state(self.p, Draft.EDITOR), messages.SKIPPED)
        self.assertEqual(board.item_state(self.p), messages.SKIPPED)
        self.assertFalse(board.has_post(self.p, Draft.EDITOR))
        target = notion_sync.Target(notion_sync.KIT, [self.p], [(self.p, Draft.EDITOR, '질문')],
                                     '자료', date(2026, 10, 14), '허브')
        self.assertEqual(notion_sync._progress_states(target, [messages.SKIPPED]), [])

    def test_kit_hub_shows_recruit_posted_and_question_skipped(self):
        Draft.objects.create(proposal=self.p, channel=Draft.RECRUIT, body='서평단', status=Draft.POSTED)
        self.assertIn('서평단 ✅ 올림', self.labels())
        self.assertIn('편집 후기 질문 넘김', self.labels())

    def test_kit_hub_shows_completed_editor_post_instead_of_original_question(self):
        Draft.objects.create(proposal=self.p, channel=Draft.EDITOR, body='편집 일기', version=2,
                             extra={'form': 'post'}, status=Draft.POSTED, parent=self.q)
        self.assertIn('편집 후기 ✅ 올림', self.labels())
        self.assertNotIn('편집 후기 질문 넘김', self.labels())
