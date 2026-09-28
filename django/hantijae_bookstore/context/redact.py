"""대화 기록용 가림. 원문은 저장하지 않으므로 여기서 가린 결과가 유일한 기록이다. 애매하면 가린다.

- 워커가 메시지마다 바로 부르므로 모든 반복에 상한을 두고, 주소는 낱말 첫머리에서만 시작한다(긴 한글에서 폭주 방지).
- 적용 순서가 중요하다: 전화를 낱말 없는 계좌(b)보다 먼저 가려야 010-1234-5678 이 [계좌]가 되지 않는다.
"""
import re
from collections import Counter

LABELS = {'password': '비밀번호', 'rrn': '주민번호', 'card': '카드', 'account': '계좌', 'phone': '전화',
          'email': '이메일', 'address': '주소'}

# 비밀번호: 낱말 뒤 같은 줄·다음 줄(최대 80자)에서 비밀번호처럼 생긴 첫 토큰을 가린다.
# "비밀번호가 abc123", "비번 알려드릴게요 abc123", "비번은 다음과 같아요\nabc123" 처럼 한국어 말이 먼저 와도 잡는다.
_PW_WORD = re.compile(r'(?i)(?<![A-Za-z])(?:비번|비밀\s?번호|패스워드|암호(?![가-힣])|password|passwd|pass|pwd|pw)(?![A-Za-z])')
_PW_WINDOW = 80
_TOKEN = re.compile(r'\S+')
_ASCII_RUN = re.compile(r'[\x21-\x7E]+')
_HANGUL_THEN_CODE = re.compile(r'[가-힣]+[A-Za-z0-9!@#$%^&*._-]{2,}\S*')
_COUNTER = re.compile(r'(?:년|월|일|시|분|초|자|글자|개|번|권|명|원|쪽|회|차|층|호|동|곳|주|쇄|부|장|건|만|천|억|배|%)')
_DATE_LIKE = re.compile(r'\d{2,4}[-./]\d{1,2}(?:[-./]\d{1,2})?[.,]?|\d{1,2}:\d{2}')
_RRN = re.compile(r'(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?:\s?-\s?|\s)?[1-4]\d{6}(?!\d)')
_CARD = re.compile(r'(?<!\d)\d{4}([- ])\d{4}\1\d{4}\1\d{4}(?!\d)')
_BANK = ('은행|농협|신한|국민|우리|하나|기업|카카오뱅크|카뱅|케이뱅크|토스|새마을|신협|우체국|수협|씨티|SC제일|'
         '부산|대구|경남|광주|전북|제주|계좌|입금')
_ACCOUNT_A = re.compile(rf'(?:{_BANK})[^\d\n\[]{{0,20}}?(?<![\d-])(\d{{1,14}}(?:-\d{{1,14}}){{1,4}}|\d{{1,14}}(?: \d{{1,14}}){{1,4}}|\d{{10,14}})(?![\d-])')
_PHONE = re.compile(r'(?<![\d-])\(?(?:\+82[-. ]?(?:\(0\))?|0)(?:1[016789]|2|[3-6]\d|70|80|50\d?)(?:\)\s?|[-. ])?\d{3,4}[-. ]?\d{4}(?![\d-])')
_ACCOUNT_B = re.compile(r'(?<![\d-])\d{1,7}(?:-\d{1,7}){2,4}(?![\d-])')
_EMAIL = re.compile(r'(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,5}')
# 계정을 알려 주는 메시지에서는 '아이디(이메일) 비밀번호' 순서로 적기도 한다 → 이메일 바로 뒤 영문·숫자 토큰
_LOGIN_WORDS = re.compile(r'(?i)비번|비밀\s?번호|패스워드|암호|password|passwd|(?<![A-Za-z])(?:pw|pwd|pass)(?![A-Za-z])|로그인|계정')
_AFTER_EMAIL = re.compile(r'(\[이메일\][ \t]*(?:[/,|][ \t]*)?\n?[ \t]*)([^\s가-힣\[\]]{4,})')

# 주소: [시·도] [시·군·구 1~2개] [읍·면] 도로·동·리 + 번지 [+ 건물·동·호·층] [(참고)].
# 시·구 자리에는 3글자 이상이거나 중·동·서·남·북구만 받는다 — '혹시', '다시', '친구' 같은 말이 시·구로 읽히지 않게.
_CITY = (r'(?:[가-힣]{1,6}(?:특별시|광역시|특별자치시|특별자치도|도)|'
         r'서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)')
_UNIT = r'(?:[가-힣]{2,6}(?:시|군|구)|[중동서남북]구)\s+'
_TOWN = r'(?:[가-힣]{1,8}(?:읍|면)\s+)?'
_ROAD = r'[가-힣0-9]{1,12}(?:로|길|동|읍|면|리|가)(?:\s?\d{1,4}(?:번)?(?:길|가))?\s*\d{1,5}(?:-\d{1,5})?(?:번지)?'   # 와우산로 29길, 남산동 2가
# 번지 뒤에 수량·시간 단위가 오면 주소가 아니다('택배로 20권', '이동 2시간')
_NOT_QUANTITY = r'(?![\d-])(?!\s*(?:권|부|명|개|시간|시|분|초|년|월|일|번(?!지)|쇄|곳|주|쪽|원|장|회|건|차|인|살|세|만|천|억|배|위|등|편|마리|%))'
_DETAIL = (r'(?:\s{0,3},?\s{0,3}(?:[가-힣A-Za-z]{1,12}\s{0,3})?(?:[A-Za-z]|[A-Za-z]?\d{1,5}(?:-\d{1,5})?[A-Za-z]?)\s{0,3}(?:동|호실|호|층)'
           r'|\s{0,3},?\s{0,3}[가-힣A-Za-z0-9]{1,12}(?:아파트|빌딩|빌라|맨션|오피스텔|타워|하우스)){0,4}')
_ADDRESS = re.compile(
    rf'(?<![가-힣])(?:\(\d{{5}}\)\s?)?(?:{_CITY}\s?(?:{_UNIT}){{0,2}}|(?:{_UNIT}){{1,2}}){_TOWN}{_ROAD}{_NOT_QUANTITY}{_DETAIL}'
    r'(?:\s{0,3}\([^)\n]{0,30}\))?')


def _password_span(token):
    """토큰 안에서 비밀번호로 볼 (시작, 끝). 비밀번호를 이야기만 하는 말('찾기', '8자리', '2026년')이면 None."""
    if '@' in token:
        return None       # 이메일은 이메일 규칙이 가리고, 그 뒤 토큰을 _AFTER_EMAIL 이 본다
    start = len(token) - len(token.lstrip(':=：'))
    rest = token[start:]
    run = _ASCII_RUN.match(rest)
    if run and len(run.group()) >= 4:
        value, tail = run.group(), rest[run.end():]
        if value.isdigit() and _COUNTER.match(tail):
            return None
        if _DATE_LIKE.fullmatch(value):
            return None
        return start, start + len(value)
    if _HANGUL_THEN_CODE.fullmatch(rest):
        return start, len(token)
    return None


def _mask_passwords(text, counts):
    out, pos = [], 0
    for word in _PW_WORD.finditer(text):
        if word.start() < pos:
            continue
        line_end = text.find('\n', word.end())
        next_end = -1 if line_end == -1 else text.find('\n', line_end + 1)
        stop = min(len(text) if next_end == -1 else next_end, word.end() + _PW_WINDOW)
        for tok in _TOKEN.finditer(text, word.end(), stop):
            span = _password_span(tok.group())
            if span:
                out.append(text[pos:tok.start() + span[0]] + '[비밀번호]')
                pos = tok.start() + span[1]
                counts['password'] += 1
                break
    out.append(text[pos:])
    return ''.join(out)


def _digits(s):
    return sum(c.isdigit() for c in s)


def _isbn_like(text, start, number):
    return number.replace('-', '').replace(' ', '')[:3] in ('978', '979') or 'ISBN' in text[max(0, start - 8):start].upper()


def _after_email(m):
    return m.group(1) + '[비밀번호]' if _LOGIN_WORDS.search(m.string) else m.group(0)


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
    ('rrn', _RRN, lambda m: '[주민번호]'),
    ('card', _CARD, lambda m: '[카드]'),
    ('account', _ACCOUNT_A, _account_a),
    ('phone', _PHONE, lambda m: '[전화]'),
    ('account', _ACCOUNT_B, _account_b),
    ('email', _EMAIL, lambda m: '[이메일]'),
    ('password', _AFTER_EMAIL, _after_email),
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
    text = _mask_passwords(text, counts)
    for name, pattern, repl in RULES:
        text = _apply(pattern, repl, name, text, counts)
    return text, dict(counts)
