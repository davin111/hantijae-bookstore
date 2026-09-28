from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from intake.messages import tg_len
from marketing import messages
from marketing.models import Draft


def draft(pk, channel, body='본문', title='', version=1):
    return SimpleNamespace(id=pk, channel=channel, body=body, title=title, version=version,
                           label=dict(Draft.CHANNEL_CHOICES)[channel])


class MessagesTest(SimpleTestCase):
    def test_parse_cb_roundtrip_and_rejects_others(self):
        self.assertEqual(messages.parse_cb(messages.cb('sw', 12)), ('sw', 12))
        self.assertEqual(messages.parse_cb('pub:1:2'), (None, None))
        self.assertEqual(messages.parse_cb('mk:v:abc'), (None, None))

    def test_kit_caption_mentions_missing_blog_and_links(self):
        book = SimpleNamespace(title='나는 산속으로 더 깊이 들어간다', published_date=date(2026, 8, 21))
        ds = [draft(1, Draft.BLOG), draft(2, Draft.INSTAGRAM), draft(3, Draft.LINKS), draft(4, Draft.SHORT),
              draft(5, Draft.LETTER)]
        text = messages.kit_caption(book, ds, ['교보문고', '예스24'], blog_exists=False)
        self.assertTrue(text.startswith('『나는 산속으로 더 깊이 들어간다』 홍보 자료를 만들어 두었어요.'))
        self.assertIn('8월 21일에 나온 책이에요. 아직 블로그 글이 없어요.', text)
        self.assertIn('· 짧은 소개 (한 줄 3가지, 200자)', text)
        self.assertIn('사이트에 교보문고·예스24 상품 링크가 비어 있어요.', text)
        self.assertLessEqual(tg_len(text), 1024)

    def test_kit_buttons_without_blog(self):
        p = SimpleNamespace(id=7)
        kb = messages.kit_buttons(p, [draft(2, Draft.INSTAGRAM), draft(3, Draft.LINKS)])
        rows = [[b['text'] for b in row] for row in kb['inline_keyboard']]
        self.assertEqual(rows, [['인스타 글 보기'], ['나머지 보기', '이번엔 넘기기']])
        self.assertEqual(kb['inline_keyboard'][1][1]['callback_data'], 'mk:sk:7')

    def test_draft_text_and_buttons_by_channel(self):
        text = messages.draft_text(draft(9, Draft.INSTAGRAM, body='글', version=2), note='첫 줄을 줄였어요')
        self.assertTrue(text.startswith('인스타 글이에요. (고친 글 2)\n첫 줄을 줄였어요\n\n글'))
        insta = [b['text'] for b in messages.draft_buttons(draft(9, Draft.INSTAGRAM))['inline_keyboard'][0]]
        links = [b['text'] for b in messages.draft_buttons(draft(9, Draft.LINKS))['inline_keyboard'][0]]
        self.assertEqual(insta, ['올렸어요', '고치기', '다음에'])
        self.assertEqual(links, ['고치기', '다음에'])

    def test_briefing_text_has_at_most_three_items_and_measure(self):
        ps = [SimpleNamespace(id=i, headline=f'항목 {i}', reason='이유') for i in range(1, 4)]
        text = messages.briefing_text(date(2026, 9, 28), ps, measure='지난번 올린 글 ― 판매 지수 455 → 520 (2주 뒤)')
        self.assertTrue(text.startswith('이번 주 홍보 제안 (9월 28일 ~ 10월 4일)'))
        self.assertIn('\n\n3. 항목 3\n이유', text)
        self.assertTrue(text.endswith('(2주 뒤)'))
        kb = messages.briefing_buttons(SimpleNamespace(id=5), ps)
        texts = [b['text'] for row in kb['inline_keyboard'] for b in row]
        self.assertEqual(texts, ['1번 글 보기', '2번 글 보기', '3번 글 보기', '이번 주는 넘기기'])
