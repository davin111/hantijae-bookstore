from django.test import SimpleTestCase

from context.redact import redact

MUST_MASK = [
    ('비번 hanti2026!', '비번 [비밀번호]'),
    ('알라딘 아이디 hantijae / 비밀번호: abc123', '알라딘 아이디 hantijae / 비밀번호: [비밀번호]'),
    ('PW=qwer1234 입니다', 'PW=[비밀번호] 입니다'),
    ('비번은\nzx!9876', '비번은\n[비밀번호]'),
    ('주민번호 900101-1234567 입니다', '주민번호 [주민번호] 입니다'),
    ('카드 1234-5678-9012-3456', '카드 [카드]'),
    ('농협 301-1234-5678-91 한티재', '농협 [계좌] 한티재'),
    ('입금은 신한은행 110123456789 로 해 주세요', '입금은 신한은행 [계좌] 로 해 주세요'),
    ('계좌 003-12-345678', '계좌 [계좌]'),
    ('123-456789-01-234 로 보내 주세요', '[계좌] 로 보내 주세요'),
    ('010-1234-5678', '[전화]'),
    ('연락처 01098765432', '연락처 [전화]'),
    ('053-123-4567로 전화', '[전화]로 전화'),
    ('+82 10-1234-5678', '[전화]'),
    ('대구 053-123-4567', '대구 [전화]'),
    ('메일 reader@example.com 로', '메일 [이메일] 로'),
    ('대구광역시 중구 동성로 12 3층', '[주소]'),
    ('주소: 수성구 범어로 12 101동 1203호 (범어동)', '주소: [주소]'),
    ('경북 경주시 양정로 300', '[주소]'),
]

MUST_KEEP = [
    'ISBN 979-11-92455-87-7', '9791192455877', '2026-09-29 북토크', '2026.09.29', '22,000원', '260권 주문',
    '264쪽', '14:30에 만나요', '대구 북토크 10월 3일', '수성구 도서관에서 12일', '암호화폐 이야기',
    '『무지개를 변호하다』 2쇄',
]


class RedactTest(SimpleTestCase):
    def test_must_mask(self):
        for text, expected in MUST_MASK:
            with self.subTest(text=text):
                self.assertEqual(redact(text)[0], expected)

    def test_must_keep(self):
        for text in MUST_KEEP:
            with self.subTest(text=text):
                self.assertEqual(redact(text), (text, {}))

    def test_address_does_not_eat_following_date(self):
        self.assertEqual(redact('중구 동성로 12에서 10월 3일 북토크')[0], '[주소]에서 10월 3일 북토크')

    def test_counts_per_rule(self):
        self.assertEqual(redact('010-1234-5678, 010-2222-3333 / 비번 x')[1], {'phone': 2, 'password': 1})

    def test_empty(self):
        self.assertEqual(redact(None), ('', {}))
        self.assertEqual(redact(''), ('', {}))
