"""LLM이 공고문에서 뽑은 신청 기간을 원문과 대조한다. 공고문 PDF는 한글 글꼴 탓에 글자 순서가 흐트러지지만 숫자는 남는다.
연도는 LLM 값을 믿지 않고 게시일로 정한다(2026 문학나눔 공고문에 '2025. 3. 30.' 같은 연도 오타가 있었다)."""
import re
from datetime import date, timedelta

MAX_DAYS = 60       # 게시일에서 마감까지 이보다 길면 신청 기간이 아닌 날짜(사업·발행 기간)로 본다(실제 7~18일)
MAX_SPAN = 45       # 신청 시작~마감이 이보다 길면 사업·제작 기간 끝을 마감으로 잘못 읽은 것으로 본다
TIME_WINDOW = 30    # 마감 날짜 뒤 이 글자 수 안에 시각 숫자가 있어야 시각을 믿는다
_ISO = re.compile(r'\s*\d{4}-(\d{1,2})-(\d{1,2})\s*')
_CLOCK = re.compile(r'\s*(\d{1,2})(?::(\d{2}))?\s*')


def _date_in_text(d):
    """'10. 12.', '10.12', '10월 12일', '4. 10.( ) 18:00' 같은 모양(월·일 앞의 0 허용)."""
    return re.compile(rf'(?<!\d)0?{d.month}\s*(?:[./]|월)\s*0?{d.day}(?!\d)')


def _resolve(value, posted_on):
    m = _ISO.fullmatch(str(value or ''))
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    for year in (posted_on.year, posted_on.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d >= posted_on:
            return d
    return None


def _checked(value, text, posted_on):
    d = _resolve(value, posted_on)
    if d is None or d > posted_on + timedelta(days=MAX_DAYS) or not _date_in_text(d).search(text):
        return None
    return d


def _clock(value, until, text):
    m = _CLOCK.fullmatch(str(value or ''))
    if not m:
        return ''
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if hour > 23 or minute > 59:
        return ''
    hour_re = re.compile(rf'(?<!\d)0?{hour}(?!\d)')
    for hit in _date_in_text(until).finditer(text):
        if hour_re.search(text, hit.end(), hit.end() + TIME_WINDOW):
            return f'{hour:02d}:{minute:02d}'
    return ''


def verify(raw, text, posted_on):
    until = _checked(raw.get('apply_until'), text, posted_on)
    start = _checked(raw.get('apply_from'), text, posted_on)
    if start and until and start > until:
        start = None
    if start and until and (until - start).days > MAX_SPAN:
        until = None
    return {'apply_from': start, 'apply_until': until,
            'until_time': _clock(raw.get('until_time'), until, text) if until else '', 'date_checked': until is not None}
