"""마케팅 비서 텔레그램 문구·버튼 (순수 함수). 콜백은 'mk:<동작>:<번호>' (64바이트 제한 안)."""
from datetime import date, timedelta

from django.utils import timezone

from intake.messages import CAPTION_LIMIT
from intake.telegram_api import keyboard
from marketing.models import Draft
from marketing.text import clip, tg_len
from marketing.timeutil import kst_today

TEXT_LIMIT = 4096
KIT_BULLET = {Draft.BLOG: '블로그 글', Draft.INSTAGRAM: '인스타 글', Draft.LINKS: '서점 링크 공지',
              Draft.SHORT: '짧은 소개 (한 줄 3가지, 200자)', Draft.LETTER: '알리면 좋을 곳과 보낼 글'}
INTRO = {Draft.BLOG: '블로그 글이에요.', Draft.INSTAGRAM: '인스타 글이에요.',
         Draft.LINKS: '서점 링크 공지예요. 카톡이나 단체방에 그대로 붙이시면 돼요.',
         Draft.SHORT: '짧은 소개예요. 배너·카드·신청서에 쓰세요.', Draft.LETTER: '알리면 좋을 곳과 보낼 글이에요.'}


def cb(action, pk):
    return f'mk:{action}:{pk}'


def parse_cb(data):
    parts = (data or '').split(':')
    if len(parts) != 3 or parts[0] != 'mk' or not parts[2].isdigit():
        return None, None
    return parts[1], int(parts[2])


def kit_caption(book, drafts, missing, blog_exists, today=None):
    d, today = book.published_date, today or kst_today(timezone.now())
    year = '' if d.year == today.year else f'{d.year}년 '  # 올해 책이 아니면 연도를 붙인다
    lines = [f'『{book.title}』 홍보 자료를 만들어 두었어요.',
             f'{year}{d.month}월 {d.day}일에 나온 책이에요.' + ('' if blog_exists else ' 아직 블로그 글이 없어요.'),
             '', '준비된 것', *[f'· {KIT_BULLET[x.channel]}' for x in drafts]]
    if missing:
        lines += ['', f'사이트에 {"·".join(missing)} 상품 링크가 비어 있어요.']
    return clip('\n'.join(lines), CAPTION_LIMIT)


def kit_buttons(proposal, drafts):
    by = {x.channel: x for x in drafts}
    first = [(f'{by[c].label} 보기', cb('v', by[c].id)) for c in (Draft.BLOG, Draft.INSTAGRAM) if c in by]
    rows = [first] if first else []
    rows.append([('나머지 보기', cb('m', proposal.id)), ('이번엔 넘기기', cb('sk', proposal.id))])
    return keyboard(rows)


# 버튼 바로 위에 두는 안내: 누르면 무엇이 되는지 운영진이 누르기 전에 알게(2026-09-30 사용자)
GUIDE_POSTED = '[올렸어요] 올린 뒤 누르면 기록해 두고, 2주쯤 뒤 반응을 브리핑에 알려 드려요'
GUIDE_EDIT = '[고치기] 이 메시지에 답장으로 고칠 점을 적으면 다시 써 드려요'
GUIDE_LATER = '[다음에] 이번엔 쓰지 않을 때 눌러 주세요'
PLACES_HEAD = '알리면 좋을 곳'


def _button_guide(channel):
    posted = [] if channel in (Draft.LINKS, Draft.SHORT) else [GUIDE_POSTED]  # draft_buttons와 같은 기준
    return '\n'.join(posted + [GUIDE_EDIT, GUIDE_LATER])


def draft_text(draft, note=''):
    intro = INTRO[draft.channel]
    if draft.channel == Draft.LETTER and not draft.body.startswith(PLACES_HEAD):
        intro = '보낼 글이에요.'  # 보낼 곳 목록이 없는 편지에 '알리면 좋을 곳과'라고 하지 않는다
    head = intro + (f' (고친 글 {draft.version})' if draft.version > 1 else '')
    if note:
        head += '\n' + note
    body = (draft.title + '\n\n' if draft.title else '') + draft.body
    guide = _button_guide(draft.channel)
    return clip(head + '\n\n' + body, TEXT_LIMIT - tg_len(guide) - 2) + '\n\n' + guide


def draft_buttons(draft):
    if draft.channel in (Draft.LINKS, Draft.SHORT):
        return keyboard([[('고치기', cb('e', draft.id)), ('다음에', cb('l', draft.id))]])
    return keyboard([[('올렸어요', cb('p', draft.id)), ('고치기', cb('e', draft.id)), ('다음에', cb('l', draft.id))]])


def briefing_text(week_start, proposals, measure='', grants=(), sales=''):
    end = week_start + timedelta(days=6)
    lines = [f'이번 주 홍보 제안 ({week_start.month}월 {week_start.day}일 ~ {end.month}월 {end.day}일)']
    if sales:  # 전산망 최근 7일 판매 한 줄(bnk_sales.sales_line) — 보내는 때 계산해 넘긴다
        lines += ['', sales]
    for i, p in enumerate(proposals, 1):
        lines += ['', f'{i}. {p.headline}', p.reason]
        extra = getattr(p, 'extra', None) or {}
        if extra.get('link'):  # 무슨 기사·펀딩인지 운영진이 바로 열어 보게
            lines.append(f"{extra.get('link_label') or '링크'}: {extra['link']}")
    if grants:  # 열린 지원사업 공고(grants.open_calls) — 보내는 때 계산해 넘긴다
        lines += ['', '📌 지원사업 신청', *grants]
    if measure:
        lines += ['', measure]
    return clip('\n'.join(lines), TEXT_LIMIT)


def briefing_buttons(briefing, proposals):
    btns = [(f'{i}번 글 보기', cb('b', p.id)) for i, p in enumerate(proposals, 1)]
    btns.append(('이번 주는 넘기기', cb('sw', briefing.id)))
    return keyboard([btns[i:i + 2] for i in range(0, len(btns), 2)])


def midweek_text(proposals):
    lines = ['이번 주에 앞둔 일이 있어 글을 준비해 뒀어요']
    for i, p in enumerate(proposals, 1):
        lines += ['', f'{i}. {p.headline}', p.reason]
    return clip('\n'.join(lines), TEXT_LIMIT)


def midweek_buttons(proposals):
    btns = [(f'{i}번 글 보기', cb('b', p.id)) for i, p in enumerate(proposals, 1)]
    btns.append(('넘기기', cb('sn', proposals[0].id)))
    return keyboard([btns[i:i + 2] for i in range(0, len(btns), 2)])


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
    v = call.verdict or {}
    until = grant_deadline(call)
    if not until:
        lines = ['신청 기간은 공고에서 확인해 주세요']
    elif v.get('apply_from'):
        lines = [f'신청 {_day(date.fromisoformat(v["apply_from"]))} ~ {until}']
    else:
        lines = [f'신청 마감 {until}']
    if v.get('support'):
        lines.append(f'지원: {v["support"]}')
    if v.get('prep'):
        lines.append(f'준비: {v["prep"]}')
    lines.append(f'공고: {call.url}')
    if call.state in DECISION and call.decided_by:
        lines.append(DECISION[call.state].format(who=call.decided_by))
    return lines


def grant_card_text(calls):
    if len(calls) == 1:
        return clip('\n'.join([f'📌 지원사업 공고 — {calls[0].title}', *_grant_lines(calls[0])]), TEXT_LIMIT)
    lines = [f'📌 새 지원사업 공고 {len(calls)}건']
    for i, c in enumerate(calls, 1):
        lines += ['', f'{i}. {c.title}', *_grant_lines(c)]
    return clip('\n'.join(lines), TEXT_LIMIT)


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
        notes.append(f'{head}: {v.get("reason", "")}' + ('' if v.get('date_checked') else ' (마감일 확인 못 함)'))
    return clip('🔎 미리보기 — 검수 방에는 /grant live 뒤에 가요\n\n' + grant_card_text(calls) + '\n\n' + '\n'.join(notes),
                TEXT_LIMIT)


def grant_reminder_text(call):
    return f'⏰ 모레 {grant_deadline(call)}에 신청이 마감돼요 — {call.title}\n공고: {call.url}'


def grant_briefing_lines(calls):
    out = []
    for c in calls:
        until = grant_deadline(c)
        out.append(f'· {c.title} — ' + (f'{until} 마감' if until else '마감은 공고에서 확인')
                   + (' (신청하기로 함)' if c.state == 'applying' else ''))
    return out
