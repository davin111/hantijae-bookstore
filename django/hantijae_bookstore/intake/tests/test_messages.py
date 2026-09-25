from django.test import SimpleTestCase

from intake import messages

SNAP = {'title': '무지개를 변호하다', 'subtitle': '트랜스젠더 변호사 박한희의 삶과 생각',
        'authors': [{'name': '박한희', 'role': '지은이'}, {'name': '홍길동', 'role': '옮긴이'}],
        'series': '팸플릿', 'series_number': '029', 'category': '에세이', 'size': '130*200', 'page_count': 264,
        'full_price': 22000, 'isbn': '979-11-92455-87-7', 'published_date': '2026-06-01',
        'short_description': '요약', 'description': '서평'}


class MessagesTest(SimpleTestCase):
    def test_caption_contents(self):
        cap = messages.draft_caption(SNAP, [
            {'code': 'a', 'message': '가격 확인', 'blocking': False, 'audience': 'family'},
            {'code': 'b', 'message': 'ISBN 중복', 'blocking': True, 'audience': 'family'},
            {'code': 'c', 'message': '관리자용', 'blocking': False, 'audience': 'admin'}], 'https://x/book=1?preview=t')
        self.assertIn('📕 무지개를 변호하다', cap)
        self.assertIn('박한희 지음 · 홍길동 옮김', cap)
        self.assertIn('팸플릿 029 · 22,000원 · 264쪽 · 130*200 · 2026-06-01', cap)
        self.assertIn('🚫 ISBN 중복', cap)
        self.assertIn('⚠️ 가격 확인', cap)
        self.assertNotIn('관리자용', cap)
        self.assertIn('https://x/book=1?preview=t', cap)

    def test_caption_is_truncated_to_1024(self):
        many = [{'code': str(i), 'message': '아주 긴 경고 문장입니다 ' * 5, 'blocking': False, 'audience': 'family'}
                for i in range(30)]
        cap = messages.draft_caption(dict(SNAP, subtitle='부제' * 300), many, 'https://x/p')
        self.assertLessEqual(len(cap), messages.CAPTION_LIMIT)
        self.assertIn('https://x/p', cap)          # 링크는 잘리지 않는다
        self.assertIn('외', cap)

    def test_callback_data_fits_64_bytes(self):
        big = 10 ** 9
        for kb in (messages.draft_buttons(big, big), messages.confirm_buttons('pub', big, big),
                   messages.patch_buttons(big), messages.undo_buttons(big)):
            for row in kb['inline_keyboard']:
                for b in row:
                    self.assertLessEqual(len(b['callback_data'].encode()), 64)

    def test_patch_text_and_questions(self):
        text = messages.patch_text(SNAP, [{'field': 'subtitle', 'new_value': '트랜스젠더 변호사 박한희의 삶과 싸움'}], [])
        self.assertIn('• 부제: 트랜스젠더 변호사 박한희의 삶과 생각 → 트랜스젠더 변호사 박한희의 삶과 싸움', text)
        self.assertIn('❓ 어느 쪽 가격인가요?', messages.patch_text(SNAP, [], ['어느 쪽 가격인가요?']))

    def test_parse_callback(self):
        self.assertEqual(messages.parse_callback('pubok:12:3'), ('pubok', [12, 3]))
        self.assertEqual(messages.parse_callback('noop'), ('noop', []))

    def test_caption_limit_counts_utf16_units(self):
        # 이모지는 UTF-16 두 단위라 len()보다 텔레그램 기준 길이가 길다
        many = [{'code': str(i), 'message': '가' * 40, 'blocking': i % 2 == 0, 'audience': 'family'} for i in range(40)]
        cap = messages.draft_caption(SNAP, many, 'https://x/p')
        self.assertLessEqual(messages.tg_len(cap), messages.CAPTION_LIMIT)
