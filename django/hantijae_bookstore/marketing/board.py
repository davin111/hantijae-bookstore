"""허브 메시지(브리핑·주중 제안·신간 카드)의 진행 상황판: 항목·채널 상태를 DB에서 계산하고 버튼을 다시 그린다."""
from dataclasses import dataclass

from marketing import messages
from marketing.messages import OPEN, POSTED, SKIPPED
from marketing.models import Draft, Proposal


def _state(proposal, drafts):
    """drafts는 최신 판이 앞. 올린 판이 하나라도 있으면 올림, 제안을 넘겼거나 최신 판을 [다음에] 했으면 넘김."""
    if any(d.status == Draft.POSTED for d in drafts):
        return POSTED
    if proposal.status == Proposal.SKIPPED or (drafts and drafts[0].status == Draft.SKIPPED):
        return SKIPPED
    return OPEN


def channel_state(proposal, channel):
    return _state(proposal, list(proposal.drafts.filter(channel=channel).order_by('-version', '-id')))


def item_state(proposal):
    if proposal.status == Proposal.ACTED:
        return POSTED
    return _state(proposal, list(proposal.drafts.order_by('-version', '-id')))


@dataclass
class Hub:
    chat_id: int
    message_id: int
    buttons: dict


def shown_items(briefing):
    """보낼 때 메시지에 보인 항목 순서(보류로 빠진 항목 제외). 기록이 없던 예전 브리핑은 rank 순 전부."""
    by = {p.id: p for p in briefing.items.all()}
    ids = briefing.shown or sorted(by, key=lambda i: (by[i].rank, i))
    return [by[i] for i in ids if i in by]


def midweek_items(proposal):
    return list(Proposal.objects.filter(kind=Proposal.NOW, chat_id=proposal.chat_id, message_id=proposal.message_id)
                .order_by('rank', 'id'))


def kit_drafts(proposal):
    return list(proposal.drafts.filter(parent__isnull=True).order_by('id'))


def _url(obj):
    return (obj.notion or {}).get('url', '')


def briefing_hub(briefing):
    if not (briefing.chat_id and briefing.message_id):
        return None
    ps = shown_items(briefing)
    return Hub(briefing.chat_id, briefing.message_id,
               messages.briefing_buttons(briefing, ps, [item_state(p) for p in ps], _url(briefing)))


def hub_of(proposal):
    """이 제안이 들어 있는 허브. 기록되지 않은 미리보기(관리자 방 /brief·/kit)면 None."""
    if proposal.kind == Proposal.BRIEF_ITEM:
        return briefing_hub(proposal.briefing) if proposal.briefing_id else None
    if not (proposal.chat_id and proposal.message_id):
        return None
    if proposal.kind == Proposal.NOW:
        ps = midweek_items(proposal)
        return Hub(proposal.chat_id, proposal.message_id,
                   messages.midweek_buttons(ps, [item_state(p) for p in ps], _url(ps[0])))
    states = {c: channel_state(proposal, c) for c in (Draft.BLOG, Draft.INSTAGRAM)}
    return Hub(proposal.chat_id, proposal.message_id,
               messages.kit_buttons(proposal, kit_drafts(proposal), states, _url(proposal)))


def refresh(tg, hub):
    if hub is not None:
        tg.edit_markup(hub.chat_id, hub.message_id, hub.buttons)
