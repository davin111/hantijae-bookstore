"""홍보 초안 후처리·검증 (순수 함수)."""
import re
import unicodedata
from difflib import SequenceMatcher

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


def loose_key(text):
    """글자·숫자만 남긴 비교 열쇠(문장부호·공백·낫표 무시, 소문자). 책 제목이 글에 실제로 있는지 볼 때 쓴다."""
    return re.sub(r'[^0-9A-Za-z가-힣]', '', text or '').lower()


def similarity(a, b):
    """공백을 뺀 두 글이 얼마나 같은지(0~1). 같은 글의 페북·인스타판을 찾는 데 쓴다."""
    a, b = re.sub(r'\s+', '', a or ''), re.sub(r'\s+', '', b or '')
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def won_display(n):
    return f'{round(n / 10000):,}만 원'


# 인사·맞장구 답장 판별: '좋네요', '감사합니다', 'ㅋㅋㅋ' 같은 답에는 다시쓰기(LLM)를 돌리지 않는다.
_ACK_WORDS = {
    '좋네요', '좋아요', '좋습니다', '좋다', '좋음', '좋군요', '좋은데요', '좋았어요',
    '굿', '굳', '최고', '최고예요', '최고네요', '멋져요', '멋지네요', '훌륭해요', '훌륭하네요',
    '괜찮네요', '괜찮아요', '괜찮습니다', '감사합니다', '감사해요', '감사', '고마워요', '고맙습니다', '땡큐',
    '수고하셨습니다', '수고했어요', '수고많으셨습니다', '확인', '확인했어요', '확인했습니다', '확인완료',
    '알겠습니다', '알겠어요', '알았어요', '네', '넵', '넹', '예', '넵넵', '네네', '오케이', 'ok', 'okay', '오키',
    'ㅇㅋ', 'ㅇㅇ', '올렸어요', '올렸습니다', '올림', '게시했어요', '게시했습니다',
}
_ACK_LAUGHS = {'ㅋ', 'ㅎ', 'ㅠ', 'ㅜ'}  # 웃음·감탄 한 글자 토큰. 자모라 정규화에서 지워지지 않는다
_ACK_TOKENS = _ACK_WORDS | _ACK_LAUGHS
_ACK_MAX_LEN = 20  # 이보다 길면 인사말 반복이라도 다시쓰기로 보낸다


def _ack_normalize(text):
    """NFC → 소문자 → 공백 제거 → 문장부호·기호(P*, S*)·결합표시(M*)·서식문자(Cf) 제거. 자모는 남긴다."""
    out = []
    for ch in unicodedata.normalize('NFC', text or '').lower():
        if ch.isspace():
            continue
        cat = unicodedata.category(ch)
        if cat[0] in ('P', 'S', 'M') or cat == 'Cf':
            continue
        out.append(ch)
    return ''.join(out)


def is_acknowledgement(text):
    """고맙다·좋다·확인했다는 뜻뿐인 답인가(정정·수정 요청은 아무리 짧아도 False)."""
    norm = _ack_normalize(text)
    if not norm:  # 이모지·문장부호만 있는 답
        return True
    if len(norm) > _ACK_MAX_LEN:
        return False
    reachable = [True] + [False] * len(norm)  # 앞에서부터 토큰을 이어 붙여 끝까지 닿는지 보는 DP
    for i in range(1, len(norm) + 1):
        reachable[i] = any(reachable[j] and norm[j:i] in _ACK_TOKENS for j in range(i))
    return reachable[-1]
