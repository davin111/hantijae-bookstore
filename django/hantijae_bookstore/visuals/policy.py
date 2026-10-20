"""자료 우선. AI 그림은 설명상 필요가 명시된 자연/개념 주제에만 한 장 허용한다."""
import re

REAL = re.compile(r'목차|차례|본문|책\s*속|표지|현장|기념\s*사진|인물|얼굴|작가\s*사진|저자\s*사진|갈무리|스크린샷')
THEME = re.compile(r'풍경|자연|산[속\s]|산$|들녘|숲|나무|식물|바다|계절|가을|봄|겨울|여름|개념|관계|도식|일러스트')


def illustration_decision(value, *, sensitive, requested):
    if sensitive or not isinstance(value, dict) or value.get('needed') is not True:
        return None
    if value.get('purpose') not in ('theme', 'concept'):
        return None
    reason, subject = value.get('reason'), value.get('subject')
    if not isinstance(reason, str) or not 12 <= len(reason.strip()) <= 300:
        return None
    if not isinstance(subject, str) or not 1 <= len(subject.strip()) <= 150 or REAL.search(subject):
        return None
    candidates = [s for s in requested if THEME.search(s) and not REAL.search(s)]
    if not candidates:
        return None
    return {'reason': reason.strip(), 'subject': subject.strip(), 'purpose': value['purpose']}


def card_kind(show):
    if re.search(r'글\s*카드|텍스트(?:\s*카드|로만)|글자(?:\s*카드|로만|만\s*적은)', show):
        return 'text'
    if re.search(r'목차|차례', show):
        return 'toc'
    if re.search(r'본문|책\s*속|시\s*전문', show):
        return 'inside'
    if '표지' in show:
        return 'cover'
    if re.search(r'글자|텍스트|글\s*카드', show):
        return 'text'
    if re.search(r'문구|제목|안내', show) and not REAL.search(show):
        return 'text'
    if REAL.search(show):
        return 'photo'
    if THEME.search(show):
        return 'theme'
    return 'text' if not re.search(r'사진|이미지|그림', show) else 'photo'
