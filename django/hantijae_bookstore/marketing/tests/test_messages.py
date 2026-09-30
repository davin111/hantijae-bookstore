from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from intake.messages import tg_len
from marketing import messages
from marketing.models import Draft


def draft(pk, channel, body='본문', title='', version=1, extra=None):
    return SimpleNamespace(id=pk, channel=channel, body=body, title=title, version=version, extra=extra or {},
                           label=Draft(channel=channel).label)


class MessagesTest(SimpleTestCase):
    def test_parse_cb_roundtrip_and_rejects_others(self):
        self.assertEqual(messages.parse_cb(messages.cb('sw', 12)), ('sw', 12))
        self.assertEqual(messages.parse_cb('pub:1:2'), (None, None))
        self.assertEqual(messages.parse_cb('mk:v:abc'), (None, None))

    def test_kit_caption_mentions_missing_blog_and_links(self):
        book = SimpleNamespace(title='나는 산속으로 더 깊이 들어간다', published_date=date(2026, 8, 21))
        ds = [draft(1, Draft.BLOG), draft(2, Draft.INSTAGRAM), draft(3, Draft.LINKS), draft(4, Draft.SHORT),
              draft(5, Draft.LETTER)]
        text = messages.kit_caption(book, ds, ['교보문고', '예스24'], blog_exists=False, today=date(2026, 9, 28))
        self.assertTrue(text.startswith('『나는 산속으로 더 깊이 들어간다』 홍보 자료를 만들어 두었어요.'))
        self.assertIn('\n8월 21일에 나온 책이에요. 아직 네이버 블로그 글이 없어요.', text)
        self.assertIn('· 네이버 블로그 글\n', text)
        self.assertIn('· 짧은 소개 (한 줄 3가지, 200자)', text)
        self.assertIn('사이트에 교보문고·예스24 상품 링크가 비어 있어요.', text)
        self.assertLessEqual(tg_len(text), 1024)

    def test_kit_caption_adds_year_for_books_from_another_year(self):
        book = SimpleNamespace(title='밥은 먹고 다니냐는 말', published_date=date(2025, 11, 3))
        text = messages.kit_caption(book, [], [], blog_exists=True, today=date(2026, 9, 28))
        self.assertIn('\n2025년 11월 3일에 나온 책이에요.', text)

    def test_kit_buttons_without_blog(self):
        p = SimpleNamespace(id=7)
        kb = messages.kit_buttons(p, [draft(2, Draft.INSTAGRAM), draft(3, Draft.LINKS)])
        rows = [[b['text'] for b in row] for row in kb['inline_keyboard']]
        self.assertEqual(rows, [['인스타 글 보기'], ['나머지 보기', '이번엔 넘기기']])
        self.assertEqual(kb['inline_keyboard'][1][1]['callback_data'], 'mk:sk:7')

    def test_draft_text_is_only_the_text_to_post(self):
        """2026-09-30 사용자: 복사해 붙이면 머리말·안내를 지워야 했다."""
        self.assertEqual(messages.draft_text(draft(9, Draft.INSTAGRAM, body='글\n\n#한티재', version=2)), '글\n\n#한티재')
        self.assertEqual(messages.draft_text(draft(9, Draft.BLOG, title='제목', body='글')), '제목\n\n글')
        insta = [b['text'] for b in messages.draft_buttons(draft(9, Draft.INSTAGRAM))['inline_keyboard'][0]]
        links = [b['text'] for b in messages.draft_buttons(draft(9, Draft.LINKS))['inline_keyboard'][0]]
        self.assertEqual((insta, links), (['올렸어요', '고치기', '다음에'], ['고치기', '다음에']))

    def test_places_text(self):
        brief = draft(9, Draft.LETTER, extra={'places': ['농민회', '생협']})
        self.assertEqual(messages.places_text(brief), '알리면 좋을 곳\n· 농민회\n· 생협')
        kit_letter = draft(9, Draft.LETTER, extra={'places': ['청송 신문 ― 지역 시인'], 'to': '청송 신문'})
        self.assertEqual(messages.places_text(kit_letter), '알리면 좋을 곳\n· 청송 신문 ― 지역 시인\n\n보낼 곳: 청송 신문')
        self.assertEqual(messages.places_text(draft(9, Draft.INSTAGRAM)), '')

    def test_hub_texts_end_with_one_guide(self):
        ps = [SimpleNamespace(id=1, headline='항목 1', reason='이유')]
        brief = messages.briefing_text(date(2026, 9, 28), ps, measure='측정')
        self.assertTrue(brief.endswith('\n\n' + messages.BRIEF_GUIDE))
        self.assertNotIn(messages.BRIEF_GUIDE, messages.briefing_text(date(2026, 9, 28), ps, guide=False))
        self.assertTrue(messages.midweek_text(ps).endswith(messages.BRIEF_GUIDE))
        book = SimpleNamespace(title='책', published_date=date(2026, 8, 21))
        cap = messages.kit_caption(book, [draft(1, Draft.INSTAGRAM)], [], True, today=date(2026, 9, 28))
        self.assertTrue(cap.endswith(messages.KIT_GUIDE))

    def test_long_briefing_keeps_its_tags_and_one_guide_at_the_end(self):
        """HTML 허브 글은 자르지 않는다(태그가 잘리지 않게) — 너무 길면 텔레그램 쪽이 일반 글로 보낸다(main의 방식)."""
        ps = [SimpleNamespace(id=i, headline=f'항목 {i}', reason='가' * 1500) for i in range(1, 5)]
        text = messages.briefing_text(date(2026, 9, 28), ps)
        self.assertGreater(tg_len(text), messages.TEXT_LIMIT)
        self.assertIn('<b>4. 항목 4</b>\n' + '가' * 1500, text)
        self.assertEqual((text.count('<b>'), text.count('</b>')), (5, 5))
        self.assertTrue(text.endswith('\n\n' + messages.BRIEF_GUIDE))
        self.assertEqual(text.count(messages.BRIEF_GUIDE), 1)

    def test_buttons_follow_states_and_carry_the_notion_link(self):
        ps = [SimpleNamespace(id=i) for i in (1, 2, 3)]
        kb = messages.briefing_buttons(SimpleNamespace(id=5), ps, [messages.POSTED, messages.SKIPPED, messages.OPEN],
                                       'https://notion.test/p')
        rows = kb['inline_keyboard']
        self.assertEqual([b['text'] for row in rows[:-1] for b in row],
                         ['1번 ✅ 올림', '2번 넘김', '3번 글 보기', '이번 주는 넘기기'])
        self.assertEqual(rows[-1], [{'text': '노션에서 크게 보기 ↗', 'url': 'https://notion.test/p'}])
        self.assertEqual(rows[0][0]['callback_data'], 'mk:b:1')  # 이름이 바뀌어도 누르면 글을 다시 보낸다
        no_link = messages.midweek_buttons(ps[:1])
        self.assertEqual([b['text'] for row in no_link['inline_keyboard'] for b in row], ['1번 글 보기', '넘기기'])
        kit_kb = messages.kit_buttons(SimpleNamespace(id=7), [draft(1, Draft.BLOG), draft(2, Draft.INSTAGRAM)],
                                      {Draft.BLOG: messages.POSTED})
        self.assertEqual([b['text'] for b in kit_kb['inline_keyboard'][0]], ['네이버 블로그 ✅ 올림', '인스타 글 보기'])
        kit_open = messages.kit_buttons(SimpleNamespace(id=7), [draft(1, Draft.BLOG)], {})
        self.assertEqual(kit_open['inline_keyboard'][0][0]['text'], '네이버 블로그 글 보기')
        kit_skip = messages.kit_buttons(SimpleNamespace(id=7), [draft(1, Draft.BLOG)], {Draft.BLOG: messages.SKIPPED})
        self.assertEqual(kit_skip['inline_keyboard'][0][0]['text'], '네이버 블로그 넘김')

    def test_quote_lines(self):
        hub = '이번 주 홍보 제안\n\n1. 『시월』 ― 항쟁\n이유\n\n2. 다른 것\n이유'
        self.assertEqual(messages.item_line(hub, '『시월』 ― 항쟁'), '1. 『시월』 ― 항쟁')
        self.assertIsNone(messages.item_line(hub, '없는 제목'))
        self.assertEqual(messages.line_number('2. 다른 것'), 2)
        self.assertIsNone(messages.line_number(None))
        cap = '준비된 것\n· 네이버 블로그 글\n· 인스타 글'
        self.assertEqual(messages.kit_line(cap, Draft.INSTAGRAM), '· 인스타 글')
        self.assertEqual(messages.kit_line(cap, Draft.BLOG), '· 네이버 블로그 글')
        self.assertIsNone(messages.kit_line(cap, Draft.LINKS))

    def test_quote_for_plain_hub_has_no_entities(self):
        msg = {'text': '이번 주 홍보 제안\n\n1. 항목 1\n이유'}
        self.assertEqual(messages.quote_for(msg, '1. 항목 1'), ('1. 항목 1', None))

    def test_quote_for_takes_only_the_bold_over_that_line(self):
        """굵게 줄을 인용할 때는 그 줄에 걸친 서식을 줄 기준 위치로 옮겨 같이 보내야 한다(2026-09-30 확인)."""
        text = '이번 주 홍보 제안 (9월 28일 ~ 10월 4일)\n\n1. 항목 1\n이유\n\n2. 항목 2\n이유'
        msg = {'text': text, 'entities': [
            {'type': 'bold', 'offset': 0, 'length': 10},                      # 제목
            {'type': 'bold', 'offset': 30, 'length': 7},                      # 1. 항목 1
            {'type': 'bold', 'offset': 42, 'length': 7},                      # 2. 항목 2
            {'type': 'url', 'offset': 42, 'length': 3},                       # 인용 서식이 아닌 것은 뺀다
        ]}
        self.assertEqual(text[42:49], '2. 항목 2')
        self.assertEqual(messages.quote_for(msg, '2. 항목 2'),
                         ('2. 항목 2', [{'type': 'bold', 'offset': 0, 'length': 7}]))

    def test_quote_for_clips_entities_to_the_line(self):
        msg = {'text': '머리\n1. 항목 1\n다음 줄', 'entities': [{'type': 'italic', 'offset': 6, 'length': 8},
                                                           {'type': 'bold', 'offset': 0, 'length': 5}]}
        self.assertEqual(messages.quote_for(msg, '1. 항목 1'),
                         ('1. 항목 1', [{'type': 'italic', 'offset': 3, 'length': 4},
                                      {'type': 'bold', 'offset': 0, 'length': 2}]))

    def test_quote_for_counts_utf16_units(self):
        """🎉·🌱는 UTF-16으로 2칸. 텔레그램의 offset·length는 UTF-16 단위다."""
        msg = {'text': '🎉\n2. 『책』 🌱 새싹', 'entities': [{'type': 'bold', 'offset': 13, 'length': 2},
                                                     {'type': 'custom_emoji', 'offset': 10, 'length': 2,
                                                      'custom_emoji_id': '42'}]}
        self.assertEqual(messages.quote_for(msg, '2. 『책』 🌱 새싹'),
                         ('2. 『책』 🌱 새싹', [{'type': 'bold', 'offset': 10, 'length': 2},
                                          {'type': 'custom_emoji', 'offset': 7, 'length': 2, 'custom_emoji_id': '42'}]))

    def test_quote_for_reads_captions(self):
        msg = {'caption': '준비된 것\n· 인스타 글', 'caption_entities': [{'type': 'bold', 'offset': 6, 'length': 6}],
               'entities': [{'type': 'bold', 'offset': 0, 'length': 3}]}
        self.assertEqual(messages.quote_for(msg, '· 인스타 글'), ('· 인스타 글', [{'type': 'bold', 'offset': 0, 'length': 6}]))

    def test_quote_for_missing_line(self):
        msg = {'text': '1. 항목 1', 'entities': [{'type': 'bold', 'offset': 0, 'length': 7}]}
        self.assertEqual(messages.quote_for(msg, '2. 항목 2'), (None, None))
        self.assertEqual(messages.quote_for(msg, None), (None, None))
        self.assertEqual(messages.quote_for({}, '1. 항목 1'), (None, None))
        self.assertEqual(messages.quote_for(msg, '1. 항목'), (None, None))  # 줄 일부는 줄이 아니다

    def test_plain_turns_an_html_hub_into_what_people_read(self):
        """노션 파란 상자에는 <b>·&lt; 없이 보이는 글 그대로(2026-09-30)."""
        ps = [SimpleNamespace(id=1, headline='『<지역서점>』 ― 소식 & 이야기', reason='a<b', extra={})]
        text = messages.plain(messages.briefing_text(date(2026, 9, 28), ps, guide=False))
        self.assertEqual(text, '이번 주 홍보 제안 (9월 28일 ~ 10월 4일)\n\n1. 『<지역서점>』 ― 소식 & 이야기\na<b')

    def test_toasts_pick_the_right_particle(self):
        self.assertEqual(messages.sent_toast(2, draft(1, Draft.INSTAGRAM)), '2번 인스타 글을 보냈어요')
        self.assertEqual(messages.sent_toast(None, draft(1, Draft.LINKS)), '서점 링크 공지를 보냈어요')
        self.assertEqual(messages.sent_toast(None, draft(1, Draft.SHORT)), '짧은 소개를 보냈어요')
        self.assertEqual(messages.sent_toast(1, draft(1, Draft.BLOG), 'notion'),
                         '1번 네이버 블로그 글을 보냈어요 · 노션에서 고친 글이에요')
        self.assertEqual(messages.sent_toast(None, draft(1, Draft.BLOG)), '네이버 블로그 글을 보냈어요')
        self.assertIn('비어 있어', messages.sent_toast(1, draft(1, Draft.BLOG), 'empty'))
        self.assertEqual(messages.rewrite_done('첫 줄을 줄였어요'), '고쳤어요: 첫 줄을 줄였어요')
        self.assertEqual(messages.rewrite_done(''), '고쳤어요.')

    def test_briefing_text_has_at_most_three_items_and_measure(self):
        ps = [SimpleNamespace(id=i, headline=f'항목 {i}', reason='이유') for i in range(1, 4)]
        text = messages.briefing_text(date(2026, 9, 28), ps, measure='지난번 올린 글 ― 판매 지수 455 → 520 (2주 뒤)', guide=False)
        self.assertTrue(text.startswith('<b>이번 주 홍보 제안</b> (9월 28일 ~ 10월 4일)'))
        self.assertIn('\n\n<b>3. 항목 3</b>\n이유', text)
        self.assertTrue(text.endswith('(2주 뒤)'))
        linked = [SimpleNamespace(id=1, headline='항목', reason='이유',
                                  extra={'link': 'https://news.example/a', 'link_label': '기사 원문'})]
        self.assertIn('\n\n<b>1. 항목</b>\n이유\n기사 원문: https://news.example/a', messages.briefing_text(date(2026, 9, 28), linked))
        odd = [SimpleNamespace(id=1, headline='『<지역서점>』 & 소식', reason='a<b', extra={})]
        self.assertIn('<b>1. 『&lt;지역서점&gt;』 &amp; 소식</b>\na&lt;b', messages.briefing_text(date(2026, 9, 28), odd))
        kb = messages.briefing_buttons(SimpleNamespace(id=5), ps)
        texts = [b['text'] for row in kb['inline_keyboard'] for b in row]
        self.assertEqual(texts, ['1번 글 보기', '2번 글 보기', '3번 글 보기', '이번 주는 넘기기'])


class NaverBlogWordingTest(SimpleTestCase):
    def test_blog_draft_is_called_naver_blog(self):
        # 초안 메시지는 올릴 글만(머리말 없음) — '네이버 블로그'는 허브 줄·버튼·알림에서 보인다
        self.assertEqual(messages.draft_text(draft(1, Draft.BLOG, body='본문')), '본문')
        self.assertEqual(Draft(channel=Draft.BLOG).label, '네이버 블로그 글')
        self.assertEqual(messages.KIT_BULLET[Draft.BLOG], '네이버 블로그 글')
        self.assertEqual(messages.sent_toast(None, draft(1, Draft.BLOG)), '네이버 블로그 글을 보냈어요')
