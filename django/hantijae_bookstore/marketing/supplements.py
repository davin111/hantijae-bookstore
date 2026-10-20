"""본문과 별도로 검증하는 카드 구성안·공동 게시 메모. 외부 호출이나 저장은 하지 않는다."""
import re
from copy import deepcopy

from intake.extract import is_verbatim
from marketing.text import fix_title_marks

INSTAGRAM_LIMIT = 2200
HOUSE_TAG = '#한티재의책'
SALES_WORDS = ('구매', '주문', '할인', '서점에서', '링크', 'http', '가격')
_NUMBER = re.compile(r'\d+(?:,\d{3})*(?:\.\d+)?')
_QUOTE = re.compile(r'[“"]([^”"\n]+)[”"]')
_HASHTAG = re.compile(r'#[\w가-힣]+')
_OPERATIONAL_METRIC = re.compile(
    r'대출\s*(?:횟수|건수|량|순위)|대출[^\n.!?]{0,30}\d|\d[^\n.!?]{0,30}대출'
    r'|(?:앞선|이전|지난)\s*\d+\s*(?:달|개월)\s*평균|(?:월\s*)?평균\s*\d+[\d,.]*\s*(?:회|건|번)'
    r'|\d+[\d,.]*\s*(?:번|회)\s*빌려|판매\s*지수|세일즈포인트')
_RECRUIT_CONDITION = re.compile(r'모집|신청|마감|발표|서평\s*(?:기간|올릴)|인원|선착순|증정|추첨|당첨|제공|선물|선정')
_RECRUIT_CARDS = [
    {'show': '책 표지와 제목·지은이 준비', 'text': '서평단을 모십니다'},
    {'show': '모집 안내를 적을 면 준비', 'text': '[모집 인원] · [신청 마감] · [발표]'},
    {'show': '서평 조건 [서평 올릴 곳] · [서평 기간]을 채워 넣을 면 준비',
     'text': '댓글로 읽고 싶은 이유를 한 줄 남겨 주세요'},
]


def clean(value):
    return fix_title_marks(value.strip()) if isinstance(value, str) else ''


def has_operational_metrics(text):
    """운영진용 수집 지표를 공개 원고로 옮기지 않는다. 행사·펀딩 숫자는 별개다."""
    return bool(_OPERATIONAL_METRIC.search(text or ''))


def factual(text, allowed_texts=(), memorial=False):
    """자료의 숫자 표기와 직접 인용을 확인한다. 짧은 숫자도 모집 인원·날짜가 될 수 있다."""
    source = '\n'.join(str(t or '') for t in allowed_texts)
    numbers = {x.replace(',', '') for x in _NUMBER.findall(source)}
    return (not ({x.replace(',', '') for x in _NUMBER.findall(text)} - numbers)
            and not has_operational_metrics(text)
            and all(is_verbatim(q, source) for q in _QUOTE.findall(text))
            and not (memorial and any(w in text for w in SALES_WORDS))
            # 프로필의 실제 목적지를 이 생성기는 확인하지 않는다. 공개 문구에는 넣지 않는다.
            and not re.search(r'프로필\s*링크', text))


def normalize_hashtags(value, allowed_texts=(), memorial=False):
    values = value if isinstance(value, list) else []
    tags = [HOUSE_TAG]
    for raw in values:
        tag = clean(raw)
        if _HASHTAG.fullmatch(tag) and tag not in tags and factual(tag, allowed_texts, memorial):
            tags.append(tag)
        if len(tags) == 5:
            break
    return tags


def normalize_extra(raw, allowed_texts=(), memorial=False):
    """검증된 키만 반환한다. 잘못된 보조물 때문에 정상 본문을 버리거나 인용을 자르지 않는다."""
    if not isinstance(raw, dict):
        return {}
    extra = {}
    cards = raw.get('cards')
    if isinstance(cards, list) and 3 <= len(cards) <= 6:
        valid = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            show, text = clean(card.get('show')), clean(card.get('text'))
            if (show and len(show) <= 60 and len(text) <= 40
                    and isinstance(card.get('text', ''), str)
                    and factual(show + '\n' + text, allowed_texts, memorial)):
                valid.append({'show': show, 'text': text})
        if len(valid) >= 3:
            extra['cards'] = valid
    cross = raw.get('cross')
    if isinstance(cross, dict):
        lead = clean(cross.get('lead'))
        if len(lead) > 500 or not factual(lead, allowed_texts, memorial):
            lead = ''
        extra['cross'] = {'lead': lead, 'hashtags': normalize_hashtags(cross.get('hashtags'), allowed_texts, memorial)}
    return extra


def recruit_cards(raw, allowed_texts=()):
    """미정 모집 조건·혜택은 책 자료의 숫자로도 승인할 수 없다. 그런 구성안은 안전한 빈칸 틀로 바꾼다."""
    cards = normalize_extra({'cards': raw}, allowed_texts).get('cards')
    if cards and not any(_NUMBER.search(c['show'] + '\n' + c['text'])
                         or _RECRUIT_CONDITION.search(c['show'] + '\n' + c['text']) for c in cards):
        return cards
    return deepcopy(_RECRUIT_CARDS)


def rewrite_extra(draft, out, note='', source_text='', memorial=False):
    """일반 수정의 extra를 복사한다. 검증 실패한 교체안은 기존 보조물을 덮어쓰지 않는다."""
    extra = deepcopy(getattr(draft, 'extra', None) or {})
    channel = getattr(draft, 'channel', None)
    if channel not in ('blog', 'instagram', 'recruit'):
        return extra
    proposal = getattr(draft, 'proposal', None)
    book_only = bool(proposal and proposal.candidate_key.startswith(('loan:', 'surge:')))
    book = proposal.book if book_only else None
    sources = ([source_text, book.title, book.subtitle, book.short_description] if book else [source_text]) if book_only else [source_text, note]
    # 예전 원고의 통계 카드는 새 원고에서 정상 보조물의 대체값으로 되살리지 않는다.
    if any(has_operational_metrics(str(c.get('show', '')) + '\n' + str(c.get('text', '')))
           or (book_only and not factual(str(c.get('show', '')) + '\n' + str(c.get('text', '')), sources))
           for c in extra.get('cards', []) if isinstance(c, dict)):
        extra.pop('cards', None)
    if isinstance(extra.get('cross'), dict) and (has_operational_metrics(extra['cross'].get('lead', ''))
            or (book_only and not factual(extra['cross'].get('lead', ''), sources))):
        extra['cross']['lead'] = ''
    raw = out if isinstance(out, dict) else {}
    valid = normalize_extra(raw, sources, memorial=memorial)
    if channel == 'recruit' and 'cards' in raw:
        valid['cards'] = recruit_cards(raw['cards'], [source_text, note])
    if 'cards' in valid:
        extra['cards'] = valid['cards']
    if 'cross' in valid:
        cross = raw['cross']
        # 잘못된 도입부를 빈 글로 바꿔 정상 도입부를 잃지 않게 한다.
        if not clean(cross.get('lead')) or valid['cross']['lead']:
            extra['cross'] = valid['cross']
    return extra


def cross_copy_text(title, body, hashtags):
    """길이 확인 대상: 실제로 함께 복사할 제목·본문·태그와 구분 줄바꿈 모두."""
    # 이미 본문에 있는 태그는 덧붙일 필요가 없다.
    existing = set(_HASHTAG.findall(body or ''))
    tags = [t for t in hashtags if t not in existing]
    return '\n\n'.join(p for p in (title, body, ' '.join(tags)) if p)


def supplement_text(draft, visual_status=''):
    """텔레그램과 노션의 같은 메모. 길이 초과 원고를 자동 절단하지 않는다."""
    extra = getattr(draft, 'extra', None) or {}
    cross, cards = extra.get('cross') or {}, extra.get('cards') or []
    lines = []
    if cross:
        lines = ['인스타·페북에 같이 올릴 때', '· 기본 원고는 그대로 쓰고, 도입부는 필요할 때만 바꿔 보세요.']
        if cross.get('lead'):
            lines.append('선택 도입부: ' + cross['lead'])
        stored_tags = cross.get('hashtags') if isinstance(cross.get('hashtags'), list) else []
        # 저장 때 출처를 검증했다. 표시할 때 빈 자료로 재검사하면 정상 숫자 태그까지 사라진다.
        tags = normalize_hashtags(stored_tags, stored_tags)
        lines.append('· 해시태그(인스타): ' + ' '.join(tags))
        lines.append('· 링크 안내가 필요하면 인스타 프로필의 실제 연결 주소를 먼저 확인해 주세요.')
        size = len(cross_copy_text(draft.title, draft.body, tags))
        if size > INSTAGRAM_LIMIT:
            lines.append(f'· 제목·본문·해시태그를 합하면 {size:,}자로 2,200자를 넘어요. '
                         '날짜·장소·신청 방법을 유지한 짧은본을 완결된 문단으로 다듬어 확인해 주세요.')
    if cards:
        if lines:
            lines.append('')
        lines.append(f'카드 구성안 ({len(cards)}장)')
        for i, card in enumerate(cards, 1):
            lines.append(f'{i}장 · {card["show"]}' + (f' — {card["text"]}' if card.get('text') else ''))
        lines.append(visual_status or '구성안입니다. 실제 제작 결과는 확보된 원본 자료에 따라 달라질 수 있어요.')
    return '\n'.join(lines)
