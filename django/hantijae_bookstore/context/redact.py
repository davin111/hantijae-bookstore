"""대화 기록용 가림. 원문은 저장하지 않으므로 여기서 가린 결과가 유일한 기록이다. 애매하면 가린다.

적용 순서가 중요하다: 전화를 낱말 없는 계좌(b)보다 먼저 가려야 010-1234-5678 이 [계좌]가 되지 않는다.
"""
import re
from collections import Counter

LABELS = {'password': '비밀번호', 'rrn': '주민번호', 'card': '카드', 'account': '계좌', 'phone': '전화',
          'email': '이메일', 'address': '주소'}

_PASSWORD = re.compile(r'(?i)(?<![A-Za-z])(비번|비밀번호|패스워드|암호|password|pw)'
                       r'(\s*[:=：]\s*|(?:은|는)?\s+)(?!\[)(\S+)')
_RRN = re.compile(r'(?<!\d)\d{6}\s?-\s?[1-4]\d{6}(?!\d)')
_CARD = re.compile(r'(?<!\d)\d{4}([- ])\d{4}\1\d{4}\1\d{4}(?!\d)')
_BANK = ('은행|농협|신한|국민|우리|하나|기업|카카오뱅크|카뱅|케이뱅크|토스|새마을|신협|우체국|수협|씨티|SC제일|'
         '부산|대구|경남|광주|전북|제주|계좌|입금')
_ACCOUNT_A = re.compile(rf'(?:{_BANK})[^\d\n\[]{{0,20}}?(?<![\d-])(\d+(?:-\d+){{1,4}}|\d+(?: \d+){{1,4}}|\d{{10,14}})(?![\d-])')
_PHONE = re.compile(r'(?<![\d-])(?:\+82[-. ]?(?:\(0\))?|0)(?:1[016789]|2|[3-6]\d|70)[-. )]?\d{3,4}[-. ]?\d{4}(?![\d-])')
_ACCOUNT_B = re.compile(r'(?<![\d-])\d{2,6}(?:-\d{2,6}){2,4}(?![\d-])')
_EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')
_CITY = (r'(?:[가-힣]+(?:특별시|광역시|특별자치시|특별자치도|도)|'
         r'서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)')
# 시·구·군 → 로·길·동 + 번지, 그 뒤 동·호·층·건물 이름·괄호까지. 줄 끝까지 먹지 않는다(뒤따르는 날짜를 살리려고).
_ADDRESS = re.compile(
    rf'(?:{_CITY}\s*)?(?:[가-힣]+(?:시|군|구)\s+){{1,2}}[가-힣0-9]+(?:로|길|동|읍|면|리|가)\s*\d+(?:-\d+)?(?:번지)?'
    r'(?:\s*,?\s*(?:\d+\s*(?:동|호|층)|[가-힣A-Za-z0-9]+(?:아파트|빌딩|빌라|맨션|오피스텔|타워|하우스)))*'
    r'(?:\s*\([^)\n]{0,30}\))?')


def _digits(s):
    return sum(c.isdigit() for c in s)


def _isbn_like(text, start, number):
    return number.replace('-', '').replace(' ', '')[:3] in ('978', '979') or 'ISBN' in text[max(0, start - 8):start].upper()


def _account_a(m):
    num = m.group(1)
    if not 10 <= _digits(num) <= 14 or _isbn_like(m.string, m.start(1), num) or _PHONE.fullmatch(num):
        return m.group(0)     # 전화번호는 아래 전화 규칙이 가린다
    return m.group(0)[:m.start(1) - m.start(0)] + '[계좌]'


def _account_b(m):
    num = m.group(0)
    if not 10 <= _digits(num) <= 14 or _isbn_like(m.string, m.start(), num):
        return num
    return '[계좌]'


RULES = (
    ('password', _PASSWORD, lambda m: m.group(1) + m.group(2) + '[비밀번호]'),
    ('rrn', _RRN, lambda m: '[주민번호]'),
    ('card', _CARD, lambda m: '[카드]'),
    ('account', _ACCOUNT_A, _account_a),
    ('phone', _PHONE, lambda m: '[전화]'),
    ('account', _ACCOUNT_B, _account_b),
    ('email', _EMAIL, lambda m: '[이메일]'),
    ('address', _ADDRESS, lambda m: '[주소]'),
)


def _apply(pattern, repl, name, text, counts):
    def run(m):
        out = repl(m)
        if out != m.group(0):
            counts[name] += 1
        return out
    return pattern.sub(run, text)


def redact(text):
    """(가린 글, 규칙별 건수)."""
    if not text:
        return '', {}
    counts = Counter()
    for name, pattern, repl in RULES:
        text = _apply(pattern, repl, name, text, counts)
    return text, dict(counts)
