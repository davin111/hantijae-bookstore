"""계기 날짜 확인(순수 함수). LLM이 낸 날짜가 근거 글의 날짜 표현으로 설명되는지 본다.

근거 글 하나와 그 글을 보낸 날로 '가능한 날짜' 집합을 넉넉하게 만든다(명시 날짜, 'N일', 오늘·내일, 요일, 주말).
LLM이 낸 날짜가 그 집합에 있으면 확인된 것으로 본다. 집합이 넉넉해도 되는 이유: 여기서 막으려는 건
근거 어디에도 없는 날짜를 LLM이 지어내는 경우이고, 근거에 있는 표현을 다르게 풀이하는 경우는 드물다.
"""
import re
from datetime import date, timedelta

WEEKDAYS = '월화수목금토일'
_FULL = re.compile(r'(20\d\d)\s*[년./-]\s*(\d{1,2})\s*[월./-]\s*(\d{1,2})')
# 앞이 숫자·점·빗금·하이픈이면 더 큰 숫자(연도·ISBN)의 일부라 보지 않는다
_MONTH_DAY = re.compile(r'(?<![\d./-])(\d{1,2})\s*(?:월\s*|[./-])\s*(\d{1,2})(?!\d)')
_DAY_ONLY = re.compile(r'(?<![\d./-])(\d{1,2})\s*일(?![자간])')
_RELATIVE = {'오늘': 0, '금일': 0, '내일': 1, '모레': 2, '글피': 3}
_WEEKDAY = re.compile(r'(이번\s*주|다다음\s*주|다음\s*주|담주)?\s*([월화수목금토일])요일')
_WEEK_OFFSET = {'이번주': 0, '다음주': 7, '담주': 7, '다다음주': 14}


def _add(out, y, m, d):
    try:
        out.add(date(y, m, d))
    except ValueError:
        pass


def _month_day(out, m, d, sent):
    """연도 없는 월·일: 보낸 날 기준 석 달 전 ~ 아홉 달 뒤에 드는 해."""
    for y in (sent.year - 1, sent.year, sent.year + 1):
        try:
            day = date(y, m, d)
        except ValueError:
            continue
        if sent - timedelta(days=90) <= day <= sent + timedelta(days=275):
            out.add(day)


def candidate_dates(text, sent):
    """근거 글(text)과 보낸 날(sent, KST date)로 가능한 날짜 집합."""
    text = text or ''
    out = set()
    for y, m, d in _FULL.findall(text):
        _add(out, int(y), int(m), int(d))
    for m, d in _MONTH_DAY.findall(text):
        _month_day(out, int(m), int(d), sent)
    first = sent.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    for d in _DAY_ONLY.findall(text):
        for base in (first, following):
            _add(out, base.year, base.month, int(d))
    for word, n in _RELATIVE.items():
        if word in text:
            out.add(sent + timedelta(days=n))
    monday = sent - timedelta(days=sent.weekday())
    for prefix, wd in _WEEKDAY.findall(text):
        i = WEEKDAYS.index(wd)
        key = re.sub(r'\s', '', prefix)
        if key:
            out.add(monday + timedelta(days=_WEEK_OFFSET[key] + i))
        else:  # 앞말 없는 요일: 이번 주의 그 요일(지난 일일 수도)과 다가오는 그 요일
            out.add(monday + timedelta(days=i))
            out.add(sent + timedelta(days=(i - sent.weekday()) % 7))
    if '주말' in text:
        sat = sent + timedelta(days=(5 - sent.weekday()) % 7)
        out |= {sat, sat + timedelta(days=1)}
        if re.search(r'다음\s*주말', text):
            out |= {sat + timedelta(days=7), sat + timedelta(days=8)}
    return out


def date_supported(day, evidence):
    """evidence: [(근거 글, 보낸 날)] 가운데 하나라도 day를 설명하면 True."""
    return any(day in candidate_dates(text, sent) for text, sent in evidence)


def explicit_mentions(text, ref):
    """결과 글(제목·요약)에 적힌 날짜 표현마다 그 표현이 뜻할 수 있는 날짜 집합. ref: 기준 날(근거 가운데 가장 늦은 날).
    '저녁 7시'·'80주년'처럼 날짜가 아닌 숫자는 잡지 않는다."""
    text = text or ''
    out = []
    for y, m, d in _FULL.findall(text):
        found = set()
        _add(found, int(y), int(m), int(d))
        out.append(found)
    stripped = _FULL.sub(' ', text)  # 연월일은 위에서 봤으니 월·일로 다시 세지 않는다
    for m, d in _MONTH_DAY.findall(stripped):
        found = set()
        _month_day(found, int(m), int(d), ref)
        out.append(found)
    first = ref.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    for d in _DAY_ONLY.findall(_MONTH_DAY.sub(' ', stripped)):
        found = set()
        for base in (first, following):
            _add(found, base.year, base.month, int(d))
        out.append(found)
    return [f for f in out if f]


def unsupported_mentions(text, evidence):
    """결과 글의 날짜 표현 가운데 근거로 설명되지 않는 것들(표현마다 가능한 날짜 집합)."""
    if not evidence:
        return []
    ref = max(sent for _, sent in evidence)
    pool = set()
    for body, sent in evidence:
        pool |= candidate_dates(body, sent)
    return [found for found in explicit_mentions(text, ref) if not found & pool]
