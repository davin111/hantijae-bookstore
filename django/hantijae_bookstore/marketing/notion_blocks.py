"""노션 '홍보 비서 글 모음' 블록 만들기·읽기(순수 함수, 네트워크 없음).

글 하나 = 문단 블록 하나(줄바꿈·빈 줄은 블록 안에서): 노션 앱은 블록 여러 개에 걸친 글자 선택이 불편하고,
블록 하나 안에서는 '전체 선택'이 된다(2026-09-30 스파이크). 읽을 때는 엔터로 나뉜 블록도 줄바꿈으로 잇는다.
"""
from marketing.messages import OPEN, POSTED, SKIPPED
from marketing.models import Draft

RICH_LIMIT = 2000  # 노션 rich_text 한 조각(UTF-16 단위)
DB_TITLE = '홍보 비서 글 모음'
GUIDE = '▸ 제목을 누르면 펼쳐져요. 맨 아래 📝 상자를 고쳐 쓰시면, 텔레그램에서 [글 보기]를 누를 때 고친 글이 가요.'
BOX_LABEL, OLD_BOX_LABEL = '올릴 글', '이전 글'
KINDS = ('주간 브리핑', '주중 제안', '신간 묶음')
HEADING_PREFIX = {OPEN: '', POSTED: '✅ ', SKIPPED: '넘김 · '}
TEXT_TYPES = ('paragraph', 'heading_1', 'heading_2', 'heading_3', 'quote', 'callout', 'toggle', 'to_do')
KIT_MEMO = {Draft.LINKS: '카톡이나 단체방에 그대로 붙이시면 돼요.', Draft.SHORT: '배너·카드·신청서에 쓰세요.'}
DB_PROPERTIES = {'이름': {'title': {}}, '종류': {'select': {'options': [{'name': k} for k in KINDS]}},
                 '날짜': {'date': {}}, '진행': {'rich_text': {}}}


def _chunks(text):
    out, cur, n = [], [], 0
    for ch in text:
        w = 2 if ord(ch) > 0xFFFF else 1
        if n + w > RICH_LIMIT:
            out.append(''.join(cur))
            cur, n = [], 0
        cur.append(ch)
        n += w
    if cur or not out:
        out.append(''.join(cur))
    return out


def rich(text, bold=False):
    ann = {'annotations': {'bold': True}} if bold else {}
    return [{'type': 'text', 'text': {'content': c}, **ann} for c in _chunks(text or '')]


def paragraph(text, bold=False, color='default'):
    return {'type': 'paragraph', 'paragraph': {'rich_text': rich(text, bold), 'color': color}}


def callout(text, emoji, color='default', children=None):
    body = {'rich_text': rich(text), 'icon': {'type': 'emoji', 'emoji': emoji}, 'color': color}
    if children:
        body['children'] = children
    return {'type': 'callout', 'callout': body}


def toggle_heading(text, children):
    return {'type': 'heading_3', 'heading_3': {'rich_text': rich(text), 'is_toggleable': True, 'children': children}}


def divider():
    return {'type': 'divider', 'divider': {}}


def box():
    return callout(BOX_LABEL, '📝')


def box_label(old):
    return {'callout': {'rich_text': rich(OLD_BOX_LABEL if old else BOX_LABEL)}}


def box_content(title, body):
    return ([paragraph(title, bold=True)] if title else []) + [paragraph(body)]


def heading_update(text):
    return {'heading_3': {'rich_text': rich(text), 'is_toggleable': True}}


def heading_text(label, state):
    return HEADING_PREFIX[state] + label


def progress(states):
    parts = [f'✅ {states.count(POSTED)}' if POSTED in states else '',
             f'넘김 {states.count(SKIPPED)}' if SKIPPED in states else '',
             f'남음 {states.count(OPEN)}' if OPEN in states else '']
    return ' · '.join(p for p in parts if p) or '—'


def progress_property(states):
    return {'진행': {'rich_text': rich(progress(states))}}


def page_properties(name, kind, day, states):
    return {'이름': {'title': rich(name)}, '종류': {'select': {'name': kind}},
            '날짜': {'date': {'start': day.isoformat()}}, **progress_property(states)}


def page_blocks(hub_text, sections, caution=''):
    """sections: [(제목 글, 메모 글)]. 겹은 2단까지(제목 → [메모 상자, 📝 상자]) — 상자 속 글은 따로 덧붙인다."""
    top = [callout(hub_text, '📨', 'blue_background')]
    if caution:
        top.append(callout('조심할 점\n' + caution, '⚠️', 'yellow_background'))
    top += [paragraph(GUIDE, color='gray'), divider()]
    for heading, memo in sections:
        kids = ([callout(memo, '📌', 'gray_background')] if memo else []) + [box()]
        top.append(toggle_heading(heading, kids))
    return top


def version_blocks(version, request):
    label = f'고친 글 {version}' + (f' · 요청: "{request[:30]}"' if request else '')
    return [paragraph(label, color='gray'), box()]


def _letter_lines(draft):
    extra = getattr(draft, 'extra', None) or {}
    out = ['알리면 좋을 곳: ' + ', '.join(extra['places'])] if extra.get('places') else []
    if extra.get('to'):
        out.append(f"보낼 곳: {extra['to']}")
    return out


def item_memo(proposal, draft):
    lines = [proposal.reason] if proposal.reason else []
    extra = proposal.extra or {}
    if extra.get('link'):
        lines.append(f"{extra.get('link_label') or '링크'}: {extra['link']}")
    lines.append(f'어떤 글: {draft.label}')
    return '\n'.join(lines + _letter_lines(draft))


def kit_memo(draft):
    return '\n'.join(([KIT_MEMO[draft.channel]] if draft.channel in KIT_MEMO else []) + _letter_lines(draft))


def plain(block):
    data = block.get(block.get('type'), {}) or {}
    return ''.join(x.get('plain_text', '') for x in data.get('rich_text', []))


def read_box(blocks, title_id=''):
    """📝 상자의 자식 블록 → (제목, 본문). 블록마다 한 줄로 잇는다(엔터로 나뉜 블록도 보이는 그대로)."""
    title, lines, number = '', [], 0
    for b in blocks:
        kind = b.get('type')
        if title_id and b.get('id') == title_id:
            title = plain(b)
            continue
        if kind == 'numbered_list_item':
            number += 1
            lines.append(f'{number}. {plain(b)}')
            continue
        number = 0
        if kind == 'bulleted_list_item':
            lines.append('· ' + plain(b))
        elif kind in TEXT_TYPES:
            lines.append(plain(b))
    return title.strip(), '\n'.join(lines).strip('\n')


def normalize(text):
    lines = (text or '').replace('\r\n', '\n').replace(chr(0xA0), ' ').split('\n')
    return '\n'.join(line.rstrip() for line in lines).strip()
