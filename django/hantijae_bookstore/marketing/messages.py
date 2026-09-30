"""마케팅 비서 텔레그램 문구·버튼 (순수 함수). 콜백은 'mk:<동작>:<번호>' (64바이트 제한 안)."""
import re
from datetime import date, timedelta
from html import escape

from django.utils import timezone

from intake.messages import CAPTION_LIMIT
from intake.telegram_api import keyboard, plain_text
from marketing.models import Draft
from marketing.text import clip, tg_len
from marketing.timeutil import kst_today

TEXT_LIMIT = 4096
KIT_BULLET = {Draft.BLOG: '네이버 블로그 글', Draft.INSTAGRAM: '인스타 글', Draft.LINKS: '서점 링크 공지',
              Draft.SHORT: '짧은 소개 (한 줄 3가지, 200자)', Draft.LETTER: '알리면 좋을 곳과 보낼 글'}


def h(value):
    """HTML 서식 메시지(텔레그램 parse_mode=HTML)에 넣는 바깥 글자. 책 제목의 <지역서점 …> 같은 글자가 태그로 읽히지 않게."""
    return escape(str(value), quote=False)


def plain(html_text):
    """HTML 허브 글 → 사람이 읽는 글(태그를 벗기고 &lt; 같은 글자를 되돌림). 노션 파란 상자처럼 서식 없이 옮길 때."""
    return plain_text(html_text)


def cb(action, pk):
    return f'mk:{action}:{pk}'


def parse_cb(data):
    parts = (data or '').split(':')
    if len(parts) != 3 or parts[0] != 'mk' or not parts[2].isdigit():
        return None, None
    return parts[1], int(parts[2])


PLACES_HEAD = '알리면 좋을 곳'
OPEN, POSTED, SKIPPED = 'open', 'posted', 'skipped'
# 초안 메시지는 올릴 글만 두고(복사하기 좋게), 버튼 설명은 허브 메시지에 한 번만(2026-09-30 사용자)
BRIEF_GUIDE = ('글 보기를 누르면 올릴 글만 따로 보내 드려요. 올렸으면 그 글의 [올렸어요]를 눌러 주세요(2주쯤 뒤 반응을 알려 드려요). '
               '고칠 점은 그 글에 답장으로, 안 쓸 글은 [다음에].')
KIT_GUIDE = '버튼을 누르면 올릴 글만 따로 보내 드려요. 올렸으면 [올렸어요], 고칠 점은 그 글에 답장으로.'
NOTION_BUTTON = '노션에서 크게 보기 ↗'
ITEM_LABEL = {OPEN: '{}번 글 보기', POSTED: '{}번 ✅ 올림', SKIPPED: '{}번 넘김'}
KIT_LABEL = {OPEN: '{} 글 보기', POSTED: '{} ✅ 올림', SKIPPED: '{} 넘김'}
KIT_SHORT = {Draft.BLOG: '네이버 블로그', Draft.INSTAGRAM: '인스타'}
POSTED_TOAST = '기록했어요. 어디에 올리셨는지는 봇이 찾아보고, 2주쯤 뒤 반응을 브리핑에 알려 드려요'
WORKING = '고치고 있어요. 2~3분쯤 걸려요.'
REWRITE_FAILED = '지금은 고치지 못했어요. 잠시 뒤에 다시 적어 주세요.'
TOAST_NOTE = {'notion': ' · 노션에서 고친 글이에요', 'empty': ' · 노션 글이 비어 있어 원래 글을 보냈어요'}


def _with_guide(text, guide, limit):
    """안내가 잘리지 않게 본문을 먼저 줄인다."""
    return clip(text, limit - tg_len(guide) - 2) + '\n\n' + guide


def _html_guide(text, guide):
    """HTML 허브 글 끝에 안내 한 번. 태그를 자르지 않게 줄이지 않는다(main의 HTML 서식과 같은 방식)."""
    return text + '\n\n' + h(BRIEF_GUIDE) if guide else text


def _with_notion(rows, url):
    return rows + [[{'text': NOTION_BUTTON, 'url': url}]] if url else rows


def _pairs(btns):
    return [btns[i:i + 2] for i in range(0, len(btns), 2)]


def kit_caption(book, drafts, missing, blog_exists, today=None, guide=True):
    d, today = book.published_date, today or kst_today(timezone.now())
    year = '' if d.year == today.year else f'{d.year}년 '  # 올해 책이 아니면 연도를 붙인다
    lines = [f'『{book.title}』 홍보 자료를 만들어 두었어요.',
             f'{year}{d.month}월 {d.day}일에 나온 책이에요.' + ('' if blog_exists else ' 아직 네이버 블로그 글이 없어요.'),
             '', '준비된 것', *[f'· {KIT_BULLET[x.channel]}' for x in drafts]]
    if missing:
        lines += ['', f'사이트에 {"·".join(missing)} 상품 링크가 비어 있어요.']
    text = '\n'.join(lines)
    return _with_guide(text, KIT_GUIDE, CAPTION_LIMIT) if guide else clip(text, CAPTION_LIMIT)


def kit_buttons(proposal, drafts, states=None, notion_url=''):
    states, by = states or {}, {x.channel: x for x in drafts}
    first = [(KIT_LABEL[states.get(c, OPEN)].format(KIT_SHORT[c]), cb('v', by[c].id))
             for c in (Draft.BLOG, Draft.INSTAGRAM) if c in by]
    rows = [first] if first else []
    rows.append([('나머지 보기', cb('m', proposal.id)), ('이번엔 넘기기', cb('sk', proposal.id))])
    return keyboard(_with_notion(rows, notion_url))


def draft_text(draft):
    """올릴 글 그대로(제목이 있으면 제목 한 줄 + 빈 줄 + 본문). 복사해 붙이면 지울 줄이 없게(2026-09-30 사용자)."""
    return clip((draft.title + '\n\n' if draft.title else '') + draft.body, TEXT_LIMIT)


def places_text(draft):
    """편지 앞에 따로 보내는 보낼 곳. 없으면 ''."""
    extra = getattr(draft, 'extra', None) or {}
    places, to = extra.get('places') or [], extra.get('to') or ''
    lines = [PLACES_HEAD, *[f'· {p}' for p in places]] if places else []
    if to:
        lines += ([''] if lines else []) + [f'보낼 곳: {to}']
    return clip('\n'.join(lines), TEXT_LIMIT)


def draft_buttons(draft):
    if draft.channel in (Draft.LINKS, Draft.SHORT):
        return keyboard([[('고치기', cb('e', draft.id)), ('다음에', cb('l', draft.id))]])
    return keyboard([[('올렸어요', cb('p', draft.id)), ('고치기', cb('e', draft.id)), ('다음에', cb('l', draft.id))]])


def briefing_text(week_start, proposals, measure='', grants=(), sales='', guide=True):
    """HTML 서식(send_message(html=True)): 제목·항목 굵게. 모두 앞으로 할 일이라 접지 않는다(feedback-telegram-formatting).
    guide: 버튼 안내를 끝에 한 번(노션 파란 상자에 옮길 때는 뺀다). 자르지 않는다 — 너무 길면 텔레그램 쪽이 일반 글로 보낸다."""
    end = week_start + timedelta(days=6)
    lines = [f'<b>이번 주 홍보 제안</b> ({week_start.month}월 {week_start.day}일 ~ {end.month}월 {end.day}일)']
    if sales:  # 전산망 최근 7일 판매 한 줄(bnk_sales.sales_line) — 보내는 때 계산해 넘긴다
        lines += ['', h(sales)]
    for i, p in enumerate(proposals, 1):
        lines += ['', f'<b>{i}. {h(p.headline)}</b>', h(p.reason)]
        extra = getattr(p, 'extra', None) or {}
        if extra.get('link'):  # 무슨 기사·펀딩인지 운영진이 바로 열어 보게
            lines.append(f"{h(extra.get('link_label') or '링크')}: {h(extra['link'])}")
    if grants:  # 열린 지원사업 공고(grants.open_calls) — 보내는 때 계산해 넘긴다
        lines += ['', '<b>📌 지원사업 신청</b>', *(h(g) for g in grants)]
    if measure:
        lines += ['', h(measure)]
    return _html_guide('\n'.join(lines), guide)


def _item_buttons(proposals, states):
    states = states or [OPEN] * len(proposals)
    return [(ITEM_LABEL[s].format(i), cb('b', p.id)) for i, (p, s) in enumerate(zip(proposals, states), 1)]


def briefing_buttons(briefing, proposals, states=None, notion_url=''):
    btns = _item_buttons(proposals, states) + [('이번 주는 넘기기', cb('sw', briefing.id))]
    return keyboard(_with_notion(_pairs(btns), notion_url))


def midweek_text(proposals, guide=True):
    """HTML 서식, 안내는 끝에 한 번(briefing_text와 같게)."""
    lines = ['<b>이번 주에 앞둔 일이 있어 글을 준비해 뒀어요</b>']
    for i, p in enumerate(proposals, 1):
        lines += ['', f'<b>{i}. {h(p.headline)}</b>', h(p.reason)]
    return _html_guide('\n'.join(lines), guide)


def midweek_buttons(proposals, states=None, notion_url=''):
    btns = _item_buttons(proposals, states) + [('넘기기', cb('sn', proposals[0].id))]
    return keyboard(_with_notion(_pairs(btns), notion_url))


# ---- 인용 줄·알림 ----
_ITEM = re.compile(r'(\d+)\. (.*)$')


def item_line(hub_text, headline):
    """허브 글에서 'N. 제목' 줄을 찾는다(인용 답장용). 잘려서 없으면 None."""
    for line in (hub_text or '').split('\n'):
        m = _ITEM.match(line)
        if m and m.group(2) == headline:
            return line
    return None


def line_number(line):
    m = _ITEM.match(line or '')
    return int(m.group(1)) if m else None


def kit_line(hub_text, channel):
    line = f'· {KIT_BULLET[channel]}'
    return line if line in (hub_text or '').split('\n') else None


# 인용이 서식까지 맞아야 하는 종류(텔레그램 reply_parameters.quote_entities). 링크·멘션 같은 것은 보내지 않는다
QUOTE_ENTITY_TYPES = ('bold', 'italic', 'underline', 'strikethrough', 'spoiler', 'custom_emoji')


def quote_for(message, line):
    """(인용할 줄, 그 줄의 서식) — message는 콜백의 cq['message'](텔레그램이 서식을 뺀 text/caption과 entities를 준다).
    HTML 허브의 굵게 줄은 글만 인용하면 거절되므로(QUOTE_TEXT_INVALID, 2026-09-30 확인) 그 줄에 걸친 서식을 줄 기준
    위치(UTF-16)로 옮겨 같이 보낸다. 서식이 없으면 (줄, None), 줄이 없으면 (None, None)."""
    text = message.get('text') or message.get('caption') or ''
    entities = message.get('entities') if message.get('text') else message.get('caption_entities')
    if not line:
        return None, None
    pos = 0
    for piece in text.split('\n'):
        if piece == line:
            start = tg_len(text[:pos])
            end = start + tg_len(line)
            out = []
            for e in entities or ():
                a, b = max(e['offset'], start), min(e['offset'] + e['length'], end)
                if e.get('type') in QUOTE_ENTITY_TYPES and a < b:
                    out.append({**e, 'offset': a - start, 'length': b - a})
            return line, out or None
        pos += len(piece) + 1
    return None, None


def _obj(word):
    """목적격 조사: 받침이 있으면 '을', 없으면 '를'."""
    code = ord(word[-1]) - 0xAC00 if word else -1
    return word + ('을' if 0 <= code < 11172 and code % 28 else '를')


def sent_toast(number, draft, note=''):
    head = (f'{number}번 ' if number else '') + _obj(draft.label) + ' 보냈어요'
    return (head + TOAST_NOTE.get(note, ''))[:200]


def rewrite_done(note):
    return clip(f'고쳤어요: {note}' if note else '고쳤어요.', TEXT_LIMIT)


# ---- 지원사업 공고(marketing.grants) ----
WEEKDAYS = '월화수목금토일'
DECISION = {'applying': '✍️ {who}: 신청하기로 했어요', 'passed': '👌 {who}: 이번엔 넘겨요'}


def _day(d):
    return f'{d.month}월 {d.day}일({WEEKDAYS[d.weekday()]})'


def _clock(hhmm):
    """'16:00' → '16시', '09:30' → '9시 30분', 빈 값 → ''."""
    if not hhmm:
        return ''
    hour, minute = (int(x) for x in hhmm.split(':'))
    return f'{hour}시' + (f' {minute}분' if minute else '')


def grant_deadline(call):
    """'10월 12일(월) 16시'. 확인한 마감일이 없으면 ''."""
    if not call.apply_until:
        return ''
    clock = _clock((call.verdict or {}).get('until_time', ''))
    return _day(call.apply_until) + (f' {clock}' if clock else '')


def _grant_lines(call):
    """HTML 서식: 마감일 굵게, 바깥 글자(LLM이 뽑은 줄·이름·주소)는 h()."""
    v = call.verdict or {}
    until = grant_deadline(call)
    if not until:
        lines = ['신청 기간은 공고에서 확인해 주세요']
    elif v.get('apply_from'):
        lines = [f'신청 {_day(date.fromisoformat(v["apply_from"]))} ~ <b>{until}</b>']
    else:
        lines = [f'신청 마감 <b>{until}</b>']
    if v.get('support'):
        lines.append(f'지원: {h(v["support"])}')
    if v.get('prep'):
        lines.append(f'준비: {h(v["prep"])}')
    lines.append(f'공고: {h(call.url)}')
    if call.state in DECISION and call.decided_by:
        lines.append(DECISION[call.state].format(who=h(call.decided_by)))
    return lines


def grant_card_text(calls):
    """HTML 서식(send_message/edit_text html=True). 모두 앞으로 할 일이라 접지 않는다."""
    if len(calls) == 1:
        return '\n'.join([f'📌 <b>지원사업 공고 — {h(calls[0].title)}</b>', *_grant_lines(calls[0])])
    lines = [f'📌 <b>새 지원사업 공고 {len(calls)}건</b>']
    for i, c in enumerate(calls, 1):
        lines += ['', f'<b>{i}. {h(c.title)}</b>', *_grant_lines(c)]
    return '\n'.join(lines)


def grant_buttons(calls):
    if len(calls) == 1:
        return keyboard([[('신청할게요', cb('ga', calls[0].id)), ('이번엔 넘기기', cb('gp', calls[0].id))]])
    return keyboard([[(f'{i}번 신청할게요', cb('ga', c.id)), (f'{i}번 넘기기', cb('gp', c.id))]
                     for i, c in enumerate(calls, 1)])


def grant_preview_text(calls):
    """admin_only 미리보기(관리자 1:1, 버튼 없음). LLM이 왜 골랐는지도 보인다."""
    notes = []
    for i, c in enumerate(calls, 1):
        v = c.verdict or {}
        head = f'{i}번 판단' if len(calls) > 1 else '판단'
        notes.append(f'{head}: {h(v.get("reason", ""))}' + ('' if v.get('date_checked') else ' (마감일 확인 못 함)'))
    return '🔎 미리보기 — 검수 방에는 /grant live 뒤에 가요\n\n' + grant_card_text(calls) + '\n\n' + '\n'.join(notes)


def grant_reminder_text(call):
    return f'⏰ 모레 <b>{grant_deadline(call)}</b>에 신청이 마감돼요 — {h(call.title)}\n공고: {h(call.url)}'


def grant_briefing_lines(calls):
    out = []
    for c in calls:
        until = grant_deadline(c)
        out.append(f'· {c.title} — ' + (f'{until} 마감' if until else '마감은 공고에서 확인')
                   + (' (신청하기로 함)' if c.state == 'applying' else ''))
    return out
