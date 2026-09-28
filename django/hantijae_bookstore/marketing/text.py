"""홍보 초안 후처리·검증 (순수 함수)."""
import re

from intake.extract import is_verbatim
from intake.messages import tg_len

_TITLE_WITH_SUB = re.compile(r'『([^』―]+?)\s*―\s*([^』]+)』')
_QUOTE = re.compile(r'[“"]([^”"\n]{8,})[”"]')
# 두 자리 이하 숫자(날짜·차례)는 보지 않는다. 금액·부수·연도처럼 지어내면 곤란한 숫자만 본다.
_BIG_NUMBER = re.compile(r'\d{1,3}(?:,\d{3})+|\d{3,}')


def fix_title_marks(text):
    """『제목 ― 부제』처럼 부제가 낫표 안에 들어가면 『제목』 ― 부제로 고친다."""
    return _TITLE_WITH_SUB.sub(lambda m: f'『{m.group(1).strip()}』 ― {m.group(2).strip()}', text or '')


def unverified_quotes(text, source):
    """큰따옴표 인용(8자 이상) 가운데 원문에 그대로 없는 것."""
    return [q for q in _QUOTE.findall(text or '') if not is_verbatim(q, source)]


def _numbers(text):
    return {n.replace(',', '') for n in _BIG_NUMBER.findall(text or '')}


def foreign_numbers(text, allowed_texts):
    """초안의 세 자리 이상 숫자 가운데 허용 자료 어디에도 없는 것."""
    pool = set()
    for t in allowed_texts:
        pool |= _numbers(t)
    return sorted(_numbers(text) - pool)


def clip(text, limit):
    """텔레그램 길이(UTF-16) 기준으로 자르고 말줄임표를 붙인다."""
    if tg_len(text) <= limit:
        return text
    out = text
    while out and tg_len(out + '…') > limit:
        out = out[:-1]
    return out + '…'


def title_key(title):
    """블로그 글 제목과 책 제목을 비교할 때 쓰는 열쇠(공백·낫표 무시)."""
    return re.sub(r'[\s『』<>〈〉「」]', '', title or '')


def won_display(n):
    return f'{round(n / 10000):,}만 원'
