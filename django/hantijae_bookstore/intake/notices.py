"""첫 화면 알림 띠를 텔레그램 대화로 만든다: 운영진 글 → LLM 정리 → 검증 → 미리보기 카드 → 게시·내리기."""
import json
import re
from datetime import date, datetime, time, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from django.utils import timezone

from intake.llm import complete_json
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


def apply_fields(notice: Notice, data: dict, now=None) -> List[str]:
    """LLM이 정리한 값을 검증해 반영한다. 돌려주는 목록은 카드에 붙일 경고 문구."""
    now = now or timezone.now()
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
    notice.message = message[:200]
    notice.link_url = url
    notice.link_label = (str(data.get('link_label') or '').strip() or '자세히 보기')[:30]
    notice.starts_at, notice.ends_at = starts_at, ends_at
    if notice.state == Notice.ASKING:
        notice.state = Notice.DRAFT
    notice.save()
    return warnings


def fill_from_text(notice: Notice, text: str, llm, now=None) -> List[str]:
    now = now or timezone.now()
    user = f'운영진이 적은 글:\n{text}'
    if notice.state != Notice.ASKING:
        user += ('\n\n현재 알림(이 내용을 바탕으로 요청한 부분만 바꿔 주세요):\n'
                 + json.dumps(current_fields(notice), ensure_ascii=False))
    data = complete_json(llm, notice_system(now.astimezone(KST).date()), user)
    return apply_fields(notice, data, now)


def set_state(notice_id: int, state: str) -> Notice:
    notice = Notice.objects.filter(pk=notice_id).first()
    if notice is None or notice.state not in TRANSITIONS[state]:
        raise NoticeError('이미 처리된 알림이에요.')
    notice.state = state
    notice.save(update_fields=['state', 'updated_at'])
    return notice
