"""첫 화면 알림 띠를 텔레그램 대화로 만든다: 운영진 글 → LLM 정리 → 검증 → 미리보기 카드 → 게시·내리기."""
import json
import re
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from intake.llm import complete_json
from intake.models import FundingCampaign
from intake.prompts import notice_system
from web.models import Notice

KST = ZoneInfo('Asia/Seoul')
DEFAULT_DAYS = 30
MAX_LEN = 60
URL_RE = re.compile(r'^https?://\S+$')
# 바꿀 수 있는 상태: 게시 ← (미리보기·내림), 내림 ← (미리보기·게시)
TRANSITIONS = {Notice.POSTED: (Notice.DRAFT, Notice.REMOVED), Notice.REMOVED: (Notice.DRAFT, Notice.POSTED)}


class NoticeError(Exception):
    """검수 방에 그대로 보여 줄 수 있는 문장을 담는다."""


def kst_midnight(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=KST)


def _date(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def start(chat_id: int, prompt_message_id: int, actor: str) -> Notice:
    return Notice.objects.create(state=Notice.ASKING, chat_id=chat_id, message_id=prompt_message_id, created_by=actor)


def attach_message(notice: Notice, chat_id: int, message_id: int) -> None:
    """이후 이 메시지에 단 답장이 이 알림을 고치게 한다."""
    notice.chat_id, notice.message_id = chat_id, message_id
    notice.save(update_fields=['chat_id', 'message_id', 'updated_at'])


def current_fields(notice: Notice) -> dict:
    return {
        'message': notice.message,
        'link_url': notice.link_url or None,
        'link_label': notice.link_label,
        'start_date': notice.starts_at.astimezone(KST).date().isoformat() if notice.starts_at else None,
        'end_date': ((notice.ends_at - timedelta(seconds=1)).astimezone(KST).date().isoformat()
                     if notice.ends_at else None),
    }


def clean_fields(data: dict, now) -> Tuple[dict, List[str]]:
    """LLM이 정리한 값을 검증해 Notice 칸 값으로 바꾼다. 돌려주는 목록은 카드에 붙일 경고 문구."""
    warnings = []
    message = ' '.join(str(data.get('message') or '').split())
    if not message:
        raise NoticeError('알릴 내용을 찾지 못했어요. 무엇을 알릴지 한 번만 다시 적어 주세요.')
    url = str(data.get('link_url') or '').strip()
    if url and not URL_RE.match(url):
        warnings.append('연결 주소가 http:// 나 https:// 로 시작하지 않아 빼 두었어요.')
        url = ''
    elif url and len(url) > 500:
        warnings.append('연결 주소가 너무 길어 빼 두었어요.')
        url = ''
    raw_start, raw_end = data.get('start_date'), data.get('end_date')
    start_d, end_d = _date(raw_start), _date(raw_end)
    if (raw_start and not start_d) or (raw_end and not end_d):
        warnings.append('날짜를 알아보지 못해 기본 기간(오늘부터 30일)으로 두었어요.')
    starts_at = max(kst_midnight(start_d), now) if start_d else now
    ends_at = kst_midnight(end_d + timedelta(days=1)) if end_d else starts_at + timedelta(days=DEFAULT_DAYS)
    if ends_at <= starts_at:
        warnings.append('끝나는 날이 시작보다 앞서 기본 기간(30일)으로 두었어요.')
        ends_at = starts_at + timedelta(days=DEFAULT_DAYS)
    if len(message) > MAX_LEN:
        warnings.append(f'문구가 {MAX_LEN}자를 넘어 휴대폰에서 두 줄이 될 수 있어요.')
    return {'message': message[:200], 'link_url': url,
            'link_label': (str(data.get('link_label') or '').strip() or '자세히 보기')[:30],
            'starts_at': starts_at, 'ends_at': ends_at}, warnings


def apply_fields(notice: Notice, data: dict, now=None) -> List[str]:
    """아직 첫 화면에 없는 알림(내용 기다리는 중·미리보기)을 그 자리에서 고친다."""
    fields, warnings = clean_fields(data, now or timezone.now())
    for name, value in fields.items():
        setattr(notice, name, value)
    if notice.state == Notice.ASKING:
        notice.state = Notice.DRAFT
    notice.save()
    return warnings


def propose(notice: Notice, data: dict, now=None) -> List[str]:
    """게시 중인 알림은 수정안으로만 담아 둔다. 첫 화면은 apply_pending 전까지 그대로다."""
    now = now or timezone.now()
    fields, warnings = clean_fields(data, now)
    if fields['starts_at'] <= now:
        # 이미 떠 있는 알림이라 시작일을 '지금'으로 당기지 않는다 (문구만 고쳐도 기간이 바뀐 것처럼 보이지 않게)
        fields['starts_at'] = notice.starts_at
    notice.pending = Notice(**fields).snapshot()
    notice.save(update_fields=['pending', 'updated_at'])
    return warnings


def fill_from_text(notice: Notice, text: str, llm, now=None) -> List[str]:
    now = now or timezone.now()
    user = f'운영진이 적은 글:\n{text}'
    if notice.state != Notice.ASKING:
        base = notice.proposal() if notice.pending else notice   # 수정안이 있으면 거기서 이어 고친다
        user += ('\n\n현재 알림(이 내용을 바탕으로 요청한 부분만 바꿔 주세요):\n'
                 + json.dumps(current_fields(base), ensure_ascii=False))
    data = complete_json(llm, notice_system(now.astimezone(KST).date()), user)
    if notice.state == Notice.POSTED:
        return propose(notice, data, now)
    return apply_fields(notice, data, now)


def apply_pending(notice_id: int, now=None) -> Notice:
    """수정안을 첫 화면에 반영한다. 버튼을 두 번 눌러도 한 번만 반영되게 행을 잠근다."""
    now = now or timezone.now()
    with transaction.atomic():
        notice = Notice.objects.select_for_update().filter(pk=notice_id).first()
        if notice is None or notice.state != Notice.POSTED or not notice.pending:
            raise NoticeError('이미 처리된 알림이에요.')
        # at 은 되돌리기 버튼에 싣는 표식 — 그 뒤에 또 반영하면 옛 버튼으로는 되돌리지 못한다
        notice.previous = {'values': notice.snapshot(), 'at': int(now.timestamp() * 1000)}
        notice.set_values(notice.pending)
        notice.pending = None
        notice.save()
    return notice


def discard_pending(notice_id: int) -> Notice:
    notice = Notice.objects.filter(pk=notice_id).first()
    if notice is None or not notice.pending:
        raise NoticeError('이미 처리된 알림이에요.')
    notice.pending = None
    notice.save(update_fields=['pending', 'updated_at'])
    return notice


def undo(notice_id: int, at: Optional[int]) -> Notice:
    with transaction.atomic():
        notice = Notice.objects.select_for_update().filter(pk=notice_id).first()
        previous = notice.previous if notice else None
        if not previous:
            raise NoticeError('이미 되돌렸어요.')
        if previous['at'] != at:
            raise NoticeError('그 뒤에 알림이 또 바뀌어서 이 버튼으로는 되돌릴 수 없어요.')
        notice.set_values(previous['values'])
        notice.previous = None
        notice.save()
    return notice


def set_state(notice_id: int, state: str) -> Notice:
    notice = Notice.objects.filter(pk=notice_id).first()
    if notice is None or notice.state not in TRANSITIONS[state]:
        raise NoticeError('이미 처리된 알림이에요.')
    notice.state = state
    if state == Notice.REMOVED:
        notice.pending = None   # 내린 알림의 수정안은 버린다 (다시 띄우면 그때 값으로)
    notice.save(update_fields=['state', 'pending', 'updated_at'])
    return notice


def campaign_message(camp) -> str:
    last_day = (camp.ends_at - timedelta(seconds=1)).astimezone(KST)
    until = f'{last_day.month}월 {last_day.day}일까지'
    if camp.platform == FundingCampaign.ALADIN:
        name, where = f"『{camp.title.split(' - ')[0].strip()}』", '알라딘 북펀드'
    else:
        name, where = camp.title.strip(), '텀블벅 펀딩'
    room = MAX_LEN - len(f' {where} 진행 중 · {until}')
    if len(name) > room:
        name = name[:max(room - 1, 1)].rstrip() + '…'
    return f'{name} {where} 진행 중 · {until}'


def from_campaign(camp, now=None, post=True) -> Notice:
    """감지한 펀딩으로 알림을 만든다. 문구는 템플릿(LLM 없이) — 틀리면 카드에 답장으로 고친다."""
    now = now or timezone.now()
    notice = Notice.objects.create(message=campaign_message(camp), link_url=camp.url, link_label='함께하기',
                                   starts_at=now, ends_at=camp.ends_at,
                                   state=Notice.POSTED if post else Notice.DRAFT, created_by='북펀드 자동 감지')
    camp.notice = notice
    camp.save(update_fields=['notice', 'updated_at'])
    return notice
