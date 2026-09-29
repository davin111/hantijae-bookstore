"""마케팅 비서 텔레그램 문구·버튼 (순수 함수). 콜백은 'mk:<동작>:<번호>' (64바이트 제한 안)."""
from datetime import timedelta

from django.utils import timezone

from intake.messages import CAPTION_LIMIT
from intake.telegram_api import keyboard
from marketing.models import Draft
from marketing.text import clip
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


def draft_text(draft, note=''):
    head = INTRO[draft.channel] + (f' (고친 글 {draft.version})' if draft.version > 1 else '')
    if note:
        head += '\n' + note
    body = (draft.title + '\n\n' if draft.title else '') + draft.body
    return clip(head + '\n\n' + body, TEXT_LIMIT)


def draft_buttons(draft):
    if draft.channel in (Draft.LINKS, Draft.SHORT):
        return keyboard([[('고치기', cb('e', draft.id)), ('다음에', cb('l', draft.id))]])
    return keyboard([[('올렸어요', cb('p', draft.id)), ('고치기', cb('e', draft.id)), ('다음에', cb('l', draft.id))]])


def briefing_text(week_start, proposals, measure=''):
    end = week_start + timedelta(days=6)
    lines = [f'이번 주 홍보 제안 ({week_start.month}월 {week_start.day}일 ~ {end.month}월 {end.day}일)']
    for i, p in enumerate(proposals, 1):
        lines += ['', f'{i}. {p.headline}', p.reason]
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
