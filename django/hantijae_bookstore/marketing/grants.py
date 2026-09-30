"""진흥원 지원사업 공고 알림(스펙 .claude/docs/specs/2026-09-30-grant-calls-design.md, 로컬).
매일 06:40(KST) 한 번 사업공고 목록을 읽어 새 글을 제목 규칙과 LLM으로 거른다. 보내기·버튼은 marketing.bot이 한다."""
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import List

from django.db.models import F, Q

from intake.llm import complete_json
from intake.models import WorkerState
from marketing.doctext import document_text
from marketing.grant_dates import verify
from marketing.grant_sources import GRANT_LIST, MAX_TEXT, grant_posts, is_excluded, notice_file, view_text, view_title
from marketing.http import http_get, http_get_bytes
from marketing.models import GrantCall
from marketing.prompts import GRANT_SYSTEM, build_grant_user
from marketing.selection_sources import SPACING, kpipa_files
from marketing.text import foreign_numbers
from marketing.timeutil import kst_today

log = logging.getLogger('intake')
MODES = ('off', 'admin_only', 'live')
FRESH_DAYS = 30     # 이보다 오래된 글은 적기만 한다(첫 실행에 옛 공고가 쏟아지지 않게)
JUDGE_PER_RUN = 3   # 한 바퀴에 LLM 판단 최대 건수(워커가 텔레그램을 오래 못 보지 않게)
MAX_TRIES = 3


def mode():
    return WorkerState.get('grant_mode', 'off')


@dataclass
class ScanReport:
    new: int = 0
    ready: List[GrantCall] = field(default_factory=list)
    unannounced: List[str] = field(default_factory=list)   # 관리자 요약 줄 '· 제목 — 이유'
    gave_up: List[GrantCall] = field(default_factory=list)


def _record_new(posts, today):
    known = set(GrantCall.objects.filter(key__in=[p.key for p in posts]).values_list('key', flat=True))
    new, lines = 0, []
    for p in posts:
        if p.key in known:
            continue
        if p.posted_on < today - timedelta(days=FRESH_DAYS):
            state = GrantCall.OLD
        elif is_excluded(p.title):
            state = GrantCall.IGNORED
            lines.append(f'· {p.title} — 제목으로 뺌')
        else:
            state = GrantCall.PENDING
        GrantCall.objects.create(key=p.key, title=p.title[:300], url=p.url, posted_on=p.posted_on, state=state)
        new += 1
    return new, lines


def _read(call, get_text, get_bytes, sleep):
    """(온전한 제목, 본문 + 공고문 PDF 글자 MAX_TEXT자)."""
    page = get_text(call.url)
    parts = [view_text(page)]
    f = notice_file(kpipa_files(page))
    if f:
        sleep(SPACING)
        parts.append(document_text(f[1], get_bytes(f[0])))
    return view_title(page), '\n\n'.join(p for p in parts if p)[:MAX_TEXT]


def _line(value, allowed):
    s = ' '.join(str(value or '').split())[:120]
    return '' if foreign_numbers(s, allowed) else s


def _judge(llm, call, title, text):
    raw = complete_json(llm, GRANT_SYSTEM, build_grant_user(title, call.posted_on, text))
    dates = verify(raw, text, call.posted_on)
    allowed = [text, title]
    verdict = {'relevant': str(raw.get('relevant')).strip().lower() in ('true', '1', 'yes'),
               'reason': _line(raw.get('reason'), allowed), 'support': _line(raw.get('support'), allowed),
               'prep': _line(raw.get('prep'), allowed),
               'apply_from': dates['apply_from'].isoformat() if dates['apply_from'] else '',
               'until_time': dates['until_time'], 'date_checked': dates['date_checked']}
    return verdict, dates['apply_until']


def _evaluate(llm, today, get_text, get_bytes, sleep, report):
    for call in GrantCall.objects.filter(state=GrantCall.PENDING).order_by('posted_on', 'id')[:JUDGE_PER_RUN]:
        try:
            sleep(SPACING)
            title, text = _read(call, get_text, get_bytes, sleep)
            verdict, until = _judge(llm, call, title or call.title, text)
        except Exception:
            log.warning('grant judge failed: %s', call.key, exc_info=True)
            call.tries += 1
            if call.tries >= MAX_TRIES:
                call.state = GrantCall.SKIPPED_LLM
                report.gave_up.append(call)
            call.save(update_fields=['tries', 'state'])
            continue
        call.title = (title or call.title)[:300]
        call.verdict, call.apply_until = verdict, until
        if not verdict['relevant']:
            call.state = GrantCall.SKIPPED_LLM
            report.unannounced.append(f'· {call.title} — {verdict["reason"] or "해당 없음"}')
        elif until and until < today:
            call.state = GrantCall.OLD
        else:
            call.state = GrantCall.READY
            report.ready.append(call)
        call.save()


def scan(llm, today, get_text=http_get, get_bytes=http_get_bytes, sleep=time.sleep):
    posts = grant_posts(get_text(GRANT_LIST))
    if not posts:
        raise RuntimeError('출판진흥원 사업공고 목록에서 글을 하나도 찾지 못했어요(페이지 형식이 바뀌었을 수 있어요)')
    report = ScanReport()
    report.new, report.unannounced = _record_new(posts, today)
    _evaluate(llm, today, get_text, get_bytes, sleep, report)
    return report


def digest(report):
    """관리자 1:1 요약(알리지 않은 공고·포기한 공고). 없으면 ''."""
    parts = []
    if report.unannounced:
        parts.append('📋 알리지 않은 지원사업 공고\n' + '\n'.join(report.unannounced))
    if report.gave_up:
        parts.append('⚠️ 지원사업 공고를 3번 읽지 못해 건너뛰었어요\n'
                     + '\n'.join(f'· {c.title} {c.url}' for c in report.gave_up))
    return '\n\n'.join(parts)


PER_MESSAGE = 3     # 검수 방 카드 한 메시지에 싣는 공고 수
RECENT_DAYS = 21    # 마감을 모르는 공고를 브리핑에 붙이는 기간(게시일부터)
REMIND_DAYS = 2
CARD_ORDER = (F('apply_until').asc(nulls_last=True), 'posted_on', 'id')
STATE_LABEL = {GrantCall.IGNORED: '제목 제외', GrantCall.OLD: '지난 글', GrantCall.PENDING: '판단 전',
               GrantCall.SKIPPED_LLM: '해당 없음', GrantCall.READY: '보낼 차례', GrantCall.ANNOUNCED: '알림',
               GrantCall.APPLYING: '신청', GrantCall.PASSED: '넘김'}
USAGE = '사용법: /grant off|admin_only|live · /grant now (지금 한 번 읽기, 몇 분)'


def to_send(today):
    """아직 방에 안 간 알릴 공고. 그사이 마감이 지난 것은 old로 돌리고 뺀다."""
    GrantCall.objects.filter(state=GrantCall.READY, apply_until__lt=today).update(state=GrantCall.OLD)
    return list(GrantCall.objects.filter(state=GrantCall.READY).order_by(*CARD_ORDER))


def card_calls(chat_id, message_id):
    return list(GrantCall.objects.filter(chat_id=chat_id, message_id=message_id).order_by(*CARD_ORDER))


def open_calls(today, limit=PER_MESSAGE):
    """월요 브리핑에 붙일 열린 공고: 알렸거나 신청하기로 한 것 가운데 마감 전(마감 모름은 게시 21일 안)."""
    unknown = Q(apply_until__isnull=True, posted_on__gte=today - timedelta(days=RECENT_DAYS))
    return list(GrantCall.objects.filter(Q(apply_until__gte=today) | unknown, state__in=GrantCall.OPEN)
                .order_by(*CARD_ORDER)[:limit])


def due_reminders(today):
    return list(GrantCall.objects.filter(state=GrantCall.APPLYING, apply_until=today + timedelta(days=REMIND_DAYS),
                                         reminded_at__isnull=True, message_id__isnull=False))


def decide(call_id, applying, actor, now):
    """카드 버튼. (바뀐 공고 또는 None, 누른 사람에게 보일 짧은 답)."""
    call = GrantCall.objects.filter(pk=call_id, state__in=GrantCall.OPEN + (GrantCall.PASSED,)).first()
    if call is None:
        return None, '이미 정리된 공고예요'
    today = kst_today(now)
    if call.apply_until and call.apply_until < today:
        return None, '신청 마감이 지났어요'
    call.state = GrantCall.APPLYING if applying else GrantCall.PASSED
    call.decided_by, call.decided_at = actor[:100], now
    call.save(update_fields=['state', 'decided_by', 'decided_at'])
    if not applying:
        return call, '이번엔 넘길게요'
    if call.apply_until and (call.apply_until - today).days > REMIND_DAYS:
        return call, '마감 이틀 전에 한 번 더 알려 드릴게요'
    return call, '신청하기로 적어 뒀어요'


def status_text(today):
    rows = [f'grant_mode={mode()}', f'grant_last_scan={WorkerState.get("grant_last_scan")}']
    rows += [f'{STATE_LABEL.get(c.state, c.state)} · {c.title[:40]} · {c.apply_until or "-"}'
             for c in GrantCall.objects.order_by('-posted_on', '-id')[:8]]
    return '\n'.join(rows)
