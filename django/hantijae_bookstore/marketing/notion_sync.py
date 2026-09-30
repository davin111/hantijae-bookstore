"""노션 '홍보 비서 글 모음' 쓰기·읽기. 텔레그램은 노션 때문에 멈추지 않는다 — 쓰기 실패는 '노션 대기'로 적고 워커가 다시 한다.

쓰기 범위: 페이지는 WorkerState('marketing_notion_ds') 데이터 소스에만 만들고, 블록은 우리 기록(notion 칸)에 적힌 id에만 쓴다.
임의의 페이지·블록 id를 받는 쓰기 함수는 두지 않는다.
노션에서 고친 글은 '읽는 순간'에만 읽는다([글 보기]·[올렸어요]·고치기). 바뀜은 글 비교로만(last_edited_time은 분 단위로 반올림).
"""
import logging
from datetime import datetime, timedelta

import requests
from django.utils import timezone

from intake.models import WorkerState
from marketing import board, messages
from marketing import notion_blocks as nb
from marketing.models import Briefing, Draft, Proposal
from marketing.timeutil import in_quiet_hours, kst_today

log = logging.getLogger('intake')
SWITCH, DS = 'marketing_notion', 'marketing_notion_ds'
READ_TIMEOUT = 5
RETRY_EVERY, GIVE_UP = timedelta(minutes=10), timedelta(days=7)
BRIEF, NOW, KIT = 'brief', 'now', 'kit'
KIND_LABEL = {BRIEF: '주간 브리핑', NOW: '주중 제안', KIT: '신간 묶음'}


def enabled():
    return WorkerState.get(SWITCH, 'off') == 'on' and bool(WorkerState.get(DS))


def client_for(host):
    return getattr(host, 'notion', None) if enabled() else None


def switch(arg):
    if arg in ('on', 'off'):
        WorkerState.put(SWITCH, arg)
        return f'{SWITCH}={arg}'
    return status_line()


def status_line():
    waiting = (Briefing.objects.filter(notion__state='pending').count()
               + Proposal.objects.filter(notion__state='pending').count())
    return (f'{SWITCH}={WorkerState.get(SWITCH, "off")} ds={"있음" if WorkerState.get(DS) else "없음"} '
            f'notion_pending={waiting}')


class Target:
    """노션 페이지 한 장이 되는 허브 하나. holders: 페이지 칸(page·url·state…)을 나눠 적는 모델들.
    sections: [(제안, 채널 또는 None, 제목 글)] — 신간 묶음만 채널별 제목."""

    def __init__(self, kind, holders, sections, name, day, hub_text, caution=''):
        self.kind, self.holders, self.sections = kind, holders, sections
        self.name, self.day, self.hub_text, self.caution = name, day, hub_text, caution

    def info(self):
        return dict(self.holders[0].notion or {})

    def put(self, **fields):
        for h in self.holders:
            h.notion = {**(h.notion or {}), **fields}
            h.save(update_fields=['notion'])

    def hub(self):
        return board.briefing_hub(self.holders[0]) if self.kind == BRIEF else board.hub_of(self.holders[0])


def brief_target(briefing, hub_text):
    ps = board.shown_items(briefing)
    ws = briefing.week_start
    day = kst_today(briefing.sent_at or timezone.now())
    return Target(BRIEF, [briefing], [(p, None, f'{i}. {p.headline}') for i, p in enumerate(ps, 1)],
                  f'{ws.month}월 {ws.day}일 주 홍보 제안', day, hub_text)


def now_target(proposals, hub_text, day):
    return Target(NOW, list(proposals), [(p, None, f'{i}. {p.headline}') for i, p in enumerate(proposals, 1)],
                  f'{day.month}월 {day.day}일 주중 제안', day, hub_text)


def kit_target(proposal, hub_text, day):
    secs = [(proposal, d.channel, messages.KIT_BULLET[d.channel]) for d in board.kit_drafts(proposal)]
    return Target(KIT, [proposal], secs, f'『{proposal.book.title}』 홍보 자료', day, hub_text, proposal.caution)


def target_of(proposal):
    """상태를 다시 적을 때: 이 제안이 들어 있는 페이지. 기록이 없으면 None."""
    if proposal.kind == Proposal.BRIEF_ITEM:
        b = proposal.briefing
        return brief_target(b, (b.notion or {}).get('hub_text', '')) if b and (b.notion or {}).get('page') else None
    if not (proposal.notion or {}).get('page'):
        return None
    day = kst_today(proposal.sent_at or timezone.now())
    if proposal.kind == Proposal.NOW:
        return now_target(board.midweek_items(proposal), proposal.notion.get('hub_text', ''), day)
    return kit_target(proposal, proposal.notion.get('hub_text', ''), day)


def newest(proposal, channel=None):
    qs = Draft.objects.filter(proposal=proposal)
    if channel:
        qs = qs.filter(channel=channel)
    return qs.order_by('-version', '-id').first()


def _heading_id(proposal, channel):
    n = proposal.notion or {}
    return (n.get('headings') or {}).get(channel) if channel else n.get('heading')


def _set_heading(proposal, channel, block_id):
    n = dict(proposal.notion or {})
    if channel:
        n['headings'] = {**n.get('headings', {}), channel: block_id}
    else:
        n['heading'] = block_id
    proposal.notion = n
    proposal.save(update_fields=['notion'])


def _state(proposal, channel):
    return board.channel_state(proposal, channel) if channel else board.item_state(proposal)


def _memo(kind, proposal, channel):
    return nb.kit_memo(newest(proposal, channel)) if kind == KIT else nb.item_memo(proposal, newest(proposal))


def _fill_box(client, draft, box_id):
    res = client.append_children(box_id, nb.box_content(draft.title, draft.body))
    draft.notion = {'box': box_id, 'title': res[0]['id'] if draft.title else ''}
    draft.save(update_fields=['notion'])


def _forget(t):
    """실패한 페이지의 블록을 가리키지 않게 기록을 지운다."""
    for p, ch, _ in t.sections:
        _set_heading(p, ch, '')
        Draft.objects.filter(proposal=p, **({'channel': ch} if ch else {})).update(notion={})


def ensure_page(client, t, now):
    info = t.info()
    if info.get('state') == 'done' and info.get('url'):
        return info['url']
    page_id = None
    try:
        states = [_state(p, ch) for p, ch, _ in t.sections]
        sections = [(nb.heading_text(label, s), _memo(t.kind, p, ch)) for (p, ch, label), s in zip(t.sections, states)]
        page = client.create_page(WorkerState.get(DS), nb.page_properties(t.name, KIND_LABEL[t.kind], t.day, states),
                                  nb.page_blocks(t.hub_text, sections, t.caution))
        page_id = page['id']
        headings = [b for b in client.children(page_id, timeout=READ_TIMEOUT) if b.get('type') == 'heading_3']
        if len(headings) != len(t.sections):
            raise RuntimeError(f'노션 페이지 제목 수가 달라요: {len(headings)} != {len(t.sections)}')
        for (p, ch, _), h in zip(t.sections, headings):
            _set_heading(p, ch, h['id'])
            _fill_box(client, newest(p, ch), client.children(h['id'], timeout=READ_TIMEOUT)[-1]['id'])
        t.put(page=page_id, url=page['url'], state='done', hub_text=t.hub_text)
        return page['url']
    except Exception:
        if page_id:
            try:
                client.trash_page(page_id)
            except Exception:
                log.warning('notion trash %s failed', page_id, exc_info=True)
        _forget(t)
        t.put(page='', url='', state='pending', tries=info.get('tries', 0) + 1, last_try=now.isoformat(),
              since=info.get('since') or now.isoformat(), hub_text=t.hub_text)
        raise


def refresh(client, t):
    """항목 제목 앞 상태와 '진행' 칸을 DB 기준으로 다시 적는다(멱등). 봇이 노션에서 고치는 곳은 이 둘뿐이다."""
    if t is None or t.info().get('state') != 'done':
        return
    states, first_exc = [], None
    for p, ch, label in t.sections:
        p.refresh_from_db()
        s = _state(p, ch)
        states.append(s)
        if _heading_id(p, ch):
            try:  # 제목 하나가 지워졌어도 나머지 제목과 '진행'은 계속 고친다
                client.update_block(_heading_id(p, ch), nb.heading_update(nb.heading_text(label, s)))
            except Exception as e:
                log.warning('notion heading update failed', exc_info=True)
                first_exc = first_exc or e
    try:
        client.update_page(t.info()['page'], nb.progress_property(states))
    except Exception as e:
        first_exc = first_exc or e
    if first_exc is not None:
        raise first_exc


def append_version(client, draft, request=''):
    """텔레그램 고치기로 새로 쓴 판을 그 항목 아래에 덧붙이고, 바로 전 상자는 '이전 글'로."""
    p = Proposal.objects.get(pk=draft.proposal_id)  # 넘겨받은 객체는 낡았을 수 있다(제목 id는 페이지를 만들 때 적힌다)
    hid = _heading_id(p, draft.channel if p.kind == Proposal.KIT else None)
    if not hid:
        return False
    prev = next((x for x in Draft.objects.filter(proposal=p, channel=draft.channel, version__lt=draft.version)
                 .order_by('-version', '-id') if (x.notion or {}).get('box')), None)
    res = client.append_children(hid, nb.version_blocks(draft.version, request))
    _fill_box(client, draft, res[-1]['id'])
    if prev and prev.notion['box'] != draft.notion['box']:
        try:
            client.update_block(prev.notion['box'], nb.box_label(old=True))
        except Exception:
            log.warning('notion relabel %s failed', prev.notion['box'], exc_info=True)
    return True


def _notice(host, now, e):
    log.warning('notion read failed: %s', e)
    day = kst_today(now or timezone.now()).isoformat()
    if host is not None and WorkerState.get('marketing_error_notion_read') != day:
        WorkerState.put('marketing_error_notion_read', day)
        try:  # 알림이 실패해도 읽기는 저장된 글로 계속한다(텔레그램을 막지 않는다)
            host.notify_admin(f'⚠️ 노션 글 읽기 실패(저장된 글로 보냈어요): {type(e).__name__}: {e}')
        except Exception:
            log.warning('notion read notice failed', exc_info=True)


def current(client, proposal, channel, host=None, now=None):
    """(최신 판, 알림). 알림: '' | 'notion'(노션에서 고친 글) | 'empty'(상자가 비었거나 없어짐). client가 None이면 읽지 않는다."""
    d = newest(proposal, channel)
    if client is None or d is None:
        return d, ''
    if not (d.notion or {}).get('box'):
        has_older = any((x.notion or {}).get('box') for x in Draft.objects.filter(proposal=proposal, channel=d.channel))
        if has_older:  # 텔레그램 고치기 뒤 덧붙이기가 빠졌던 판: 지금 덧붙인다(방금 쓴 글이라 읽을 필요 없음)
            try:
                append_version(client, d)
            except Exception:
                log.warning('notion append retry failed for draft %s', d.pk, exc_info=True)
        return d, ''
    try:
        blocks = client.children(d.notion['box'], timeout=READ_TIMEOUT)
    except requests.HTTPError as e:
        if getattr(e.response, 'status_code', None) == 404:
            return d, 'empty'
        _notice(host, now, e)
        return d, ''
    except Exception as e:
        _notice(host, now, e)
        return d, ''
    title, body = nb.read_box(blocks, d.notion.get('title', ''))
    if not nb.normalize(body):
        return d, 'empty'
    if nb.normalize(title) == nb.normalize(d.title) and nb.normalize(body) == nb.normalize(d.body):
        return d, ''
    new = Draft.objects.create(proposal=proposal, channel=d.channel, title=title[:300], body=body,
                               version=d.version + 1, parent=d, origin=Draft.NOTION, extra=d.extra, notion=d.notion)
    return new, 'notion'


def pending_targets():
    out = [brief_target(b, b.notion.get('hub_text', '')) for b in Briefing.objects.filter(notion__state='pending')]
    groups = {}
    for p in Proposal.objects.filter(notion__state='pending').select_related('book').order_by('rank', 'id'):
        groups.setdefault((p.kind, p.chat_id, p.message_id) if p.kind == Proposal.NOW else ('kit', p.id), []).append(p)
    for key, ps in groups.items():
        info, day = ps[0].notion, kst_today(ps[0].sent_at or timezone.now())
        out.append(now_target(ps, info.get('hub_text', ''), day) if key[0] == Proposal.NOW
                   else kit_target(ps[0], info.get('hub_text', ''), day))
    return out


def retry_pending(host, tg, now):
    """'노션 대기' 허브를 10분마다(08~21시) 다시 만든다. 되면 텔레그램 허브에 노션 버튼을 덧단다. 7일 넘으면 멈춘다."""
    client = client_for(host)
    if client is None or in_quiet_hours(now):
        return 0
    done, first_exc = 0, None
    for t in pending_targets():
        info = t.info()
        if info.get('last_try') and now - datetime.fromisoformat(info['last_try']) < RETRY_EVERY:
            continue
        if now - datetime.fromisoformat(info.get('since') or now.isoformat()) > GIVE_UP:
            t.put(state='failed')
            host.notify_admin(f'⚠️ 노션 페이지를 7일 동안 만들지 못해 멈췄어요: {t.name}')
            continue
        try:
            ensure_page(client, t, now)
        except Exception as e:
            first_exc = first_exc or e
            continue
        done += 1
        board.refresh(tg, t.hub())
    if first_exc is not None:
        raise first_exc
    return done
