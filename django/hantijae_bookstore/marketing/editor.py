"""편집 일기: 반달마다 질문 한 번, 실제 답만 모아 작성자별 초안으로 다듬는다.

생성·관리자 미리보기·검수방 발송은 각각 기록한다. RSS 실패와 좁은 관측 범위는
미작성의 근거가 아니며, 질문 자체는 게시할 글이 아니다.
"""
import calendar
import json
import re
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Max

from intake.extract import is_verbatim
from intake.llm import LLMError, complete_json
from intake.models import WorkerState
from marketing.models import BookProfile, CopyNote, Draft, Proposal, Signal
from marketing.text import fix_title_marks, is_acknowledgement
from marketing.timeutil import kst_today

STATE = 'marketing_editor_state'
BUILD_DAYS = (1, 2, 3, 4, 5)
HEADLINE = '이번 「편집 일기」 ― 질문 세 개 준비했어요'
_NUMBER = re.compile(r'\d+(?:,\d{3})*(?:\.\d+)?')
_QUOTE = re.compile(r'"([^"]+)"|“([^”]+)”|‘([^’]+)’|(?<![A-Za-z0-9])\'([^\']+)\'')
NEUTRAL_QUESTIONS = (
    '요즘 편집실 책상 위에서 소개하고 싶은 것이 있나요?',
    '최근 책을 만드는 과정에서 기록해 두고 싶은 일이 있나요?',
    '독자에게 들려주고 싶은 작업 이야기가 있다면 무엇인가요?',
)
EDITOR_Q_SYSTEM = """한티재 운영진이 편집 일기를 시작할 수 있게 짧은 질문 세 개를 쓴다.
입력 signals는 검증·비공개 필터를 통과한 업무 요약이다. 원문 대화는 없다.
확인되지 않은 행사 참석·경험·감정이 있었다고 전제하지 않는다. 감동·보람을 유도하지 않는다.
최근 글 제목은 반복을 피하는 용도이며 그 안의 경험을 다른 사람에게 돌리지 않는다.
자료가 부족하면 있었던 일을 가정하지 않는 편집실 일상 질문을 쓴다.
자료에 없는 숫자·인용을 쓰지 않는다. JSON {"questions": ["질문", "질문", "질문"]}만 출력한다."""
EDITOR_NOTE_SYSTEM = """한티재 운영진이 실제로 답한 말만 편집 일기 초안으로 다듬는다.
운영진의 경험을 대신 만들어 쓰는 작업이 아니다. answers는 한 작성자의 답만 시간순으로 모은 것이다.
질문은 주제 안내일 뿐 사실의 근거가 아니다. book은 책 이름을 확인할 용도다.
답에 없는 일화·감정·장소·숫자·인용·인과관계는 절대 보태지 않는다. 답의 ~다/~요 말투를 살린다.
제목은 짧게, 본문은 가능하면 3~6문단. 짧은 재료는 그대로 짧게 두고 문단 수를 채우려고 늘리지 않는다.
이모지·소제목·해시태그는 쓰지 않는다. JSON {"title": "제목", "body": "본문", "note": "다듬은 점"}만 출력한다."""


def valid_facts(text, source):
    """모든 길이의 숫자 토큰·직접 인용을 확인한다. 링크 등 문구 정책은 적용하지 않는다."""
    numbers = {n.replace(',', '') for n in _NUMBER.findall(source or '')}
    if {n.replace(',', '') for n in _NUMBER.findall(text or '')} - numbers:
        return False
    return all(is_verbatim(next(q for q in match.groups() if q is not None), source)
               for match in _QUOTE.finditer(text or ''))


def period(today):
    """KST 1~15일 / 16일~말일의 (key, 시작, 끝)."""
    if isinstance(today, datetime):
        today = kst_today(today)
    half = 1 if today.day <= 15 else 2
    start = today.replace(day=1 if half == 1 else 16)
    end = today.replace(day=15 if half == 1 else calendar.monthrange(today.year, today.month)[1])
    return f'editor:{today:%Y-%m}:{half}', start, end


def period_key(today):
    return period(today)[0]


def is_current_period(proposal, today):
    return proposal.candidate_key == period_key(today)


def _record(today, now, status, reason, **fields):
    key, start, end = period(today)
    old = WorkerState.get(STATE) or {}
    if old.get('period') and old['period'] != key:
        previous = dict(old)
        if old.get('status') not in ('sent', 'posted', 'off', 'not_due'):
            previous.update(status='expired', reason=f'구간 종료: {old.get("reason", "미발송")}',
                            expired_at=now.isoformat())
        WorkerState.put('marketing_editor_previous', previous)
        old = {}
    state = {**old, 'period': key, 'start': start.isoformat(), 'end': end.isoformat(),
             'checked_at': now.isoformat(), 'status': status, 'reason': reason, **fields}
    WorkerState.put(STATE, state)
    return state


def defer(today, reason, now):
    return _record(today, now, 'deferred', reason)


def is_question(draft):
    return draft.channel == Draft.EDITOR and (draft.extra or {}).get('form') == 'questions'


def has_room_sent(proposal):
    return bool((proposal.extra or {}).get('editor_room_sent_at'))


def _skipped(proposal):
    if proposal.status == Proposal.SKIPPED:
        return True
    questions = list(proposal.drafts.filter(channel=Draft.EDITOR, extra__form='questions'))
    return bool(questions) and all(q.status == Draft.SKIPPED for q in questions)


def pending(today, room):
    """같은 구간 미발송 질문. 관리자 미리보기는 검수방 발송 기회를 소비하지 않는다."""
    key, _, _ = period(today)
    state = WorkerState.get(STATE) or {}
    if state.get('period') == key and state.get('status') in ('posted', 'sent'):
        return []
    return [p for p in Proposal.objects.filter(kind=Proposal.NOW, candidate_key=key).order_by('id')
            if not _skipped(p) and not has_room_sent(p)
            and (room or not (p.extra or {}).get('editor_preview_at'))]


def mark_generated(proposal, now):
    if proposal.candidate_key == period(now)[0]:
        _record(now, now, 'generated', '질문 생성, 검수방 발송 대기',
                proposal_id=proposal.pk, generated_at=now.isoformat())


def mark_sent(proposal, room, now):
    if not proposal.candidate_key.startswith('editor:'):
        return False
    # 지난 구간 질문은 뒤늦게 보내거나 이번 구간 완료로 기록하지 않는다.
    if proposal.candidate_key != period(now)[0]:
        return False
    if has_room_sent(proposal):
        return False
    field = 'editor_room_sent_at' if room else 'editor_preview_at'
    proposal.extra = {**(proposal.extra or {}), field: now.isoformat()}
    proposal.save(update_fields=['extra'])
    _record(now, now, 'sent' if room else 'preview', '검수방 발송 완료' if room else '관리자 미리보기, 검수방 미발송',
            proposal_id=proposal.pk, **{'room_sent_at' if room else 'preview_at': now.isoformat()})
    return True


def _unanswered(now):
    questions = Draft.objects.filter(channel=Draft.EDITOR, extra__form='questions', status=Draft.DRAFT,
                                     proposal__sent_at__gte=now - timedelta(days=14), proposal__sent_at__lte=now)
    for q in questions.select_related('proposal').order_by('-id'):
        if q.proposal.status == Proposal.SKIPPED:
            continue
        if (q.proposal.extra or {}).get('editor_preview_at') and not has_room_sent(q.proposal):
            continue
        if not q.notes.exists():
            return q
    return None


def _materials(today, now, posts):
    quiet = BookProfile.objects.filter(quiet_until__gte=today).values_list('book_id', flat=True)
    qs = (Signal.objects.filter(kind__in=(Signal.MOMENT, Signal.SOCIAL), relevant=True, sensitive=False,
                                found_at__gte=now - timedelta(days=14), found_at__lte=now)
          .exclude(book_id__in=quiet).order_by('-found_at', '-id'))
    signals = []
    for s in qs[:20]:
        summary = (s.detail or {}).get('summary')
        if isinstance(summary, str) and summary.strip():
            signals.append({'title': s.title[:300], 'summary': summary.strip()[:1000]})
    titles = [p.title for p in sorted((p for p in posts if p.date and p.date <= today),
                                    key=lambda p: p.date, reverse=True)
              if _category(p.category) == '편집 일기'][:5]
    return {'signals': signals, 'recent_titles': titles}


def _category(value):
    return ' '.join((value or '').split())


def _rss_allows(today, posts, now):
    key, start, end = period(today)
    state = WorkerState.get(STATE) or {}
    if state.get('period') == key and state.get('posted_on'):
        _record(today, now, 'posted', '이 구간 편집 일기 게시를 이미 확인함')
        return False
    if posts is None:
        _record(today, now, 'rss_failed', 'RSS 조회 실패: 게시 여부를 판단하지 않음', rss_ok=False)
        return False
    published = [p for p in posts if p.date and start <= p.date <= min(today, end)
                 and _category(p.category) == '편집 일기']
    if published:
        _record(today, now, 'posted', '이 구간 편집 일기 게시 확인', rss_ok=True,
                posted_on=max(p.date for p in published).isoformat())
        return False
    # 최근 항목만 주는 RSS가 시작일까지 닿지 못하면 글 부재를 단정하지 않는다.
    if posts and (any(p.date is None for p in posts) or min(p.date for p in posts) > start):
        _record(today, now, 'rss_partial', 'RSS 관측 범위 부족: 이 구간 전체를 확인할 수 없음', rss_ok=True)
        return False
    return True


def can_send(proposal, today, posts, now):
    """실제 발송 직전: 새 게시·RSS 실패·모드 변경·지난 구간을 LLM 없이 확인."""
    if isinstance(today, datetime):
        today = kst_today(today)
    if not is_current_period(proposal, today):
        return False
    if today.weekday() not in BUILD_DAYS:
        return False
    if WorkerState.get('editor_mode', 'off') != 'live':
        _record(today, now, 'off', '편집 일기 알림 꺼짐')
        return False
    if has_room_sent(proposal):
        _record(today, now, 'sent', '이 구간 검수방 알림 발송 완료')
        return False
    if _skipped(proposal):
        _record(today, now, 'skipped', '운영진이 질문을 다음으로 넘김')
        return False
    if not _rss_allows(today, posts, now):
        return False
    waiting = _unanswered(now)
    if waiting and waiting.proposal_id != proposal.pk:
        _record(today, now, 'waiting', '최근 14일 미답 질문 대기: 다음 제안일에 다시 확인',
                question_id=waiting.pk, rss_ok=True)
        return False
    _record(today, now, 'generated', '질문 생성, 검수방 발송 대기', rss_ok=True, proposal_id=proposal.pk)
    return True


def _questions(llm, materials):
    if not materials['signals']:
        return list(NEUTRAL_QUESTIONS), '소재 요약 없음: 중립적 질문 준비'
    out = complete_json(llm, EDITOR_Q_SYSTEM, json.dumps(materials, ensure_ascii=False))
    raw = out.get('questions')
    questions = [x.strip() for x in raw if isinstance(x, str) and x.strip()] if isinstance(raw, list) else []
    source = json.dumps(materials['signals'], ensure_ascii=False)
    if (len(questions) != 3 or any(len(q) > 300 for q in questions)
            or not valid_facts(' '.join(questions), source)):
        return list(NEUTRAL_QUESTIONS), '질문 검증 실패: 중립적 질문 준비'
    return questions, '검증된 업무 요약으로 질문 준비'


def prepare(today, posts, llm, now):
    """후보·질문 원고를 준비한다. 저장과 발송은 주중 제안 호출자가 맡는다."""
    from marketing.candidates import Candidate
    if isinstance(today, datetime):
        today = kst_today(today)
    key, start, end = period(today)
    if WorkerState.get('editor_mode', 'off') != 'live':
        _record(today, now, 'off', '편집 일기 알림 꺼짐')
        return None
    if today.weekday() not in BUILD_DAYS:
        _record(today, now, 'not_due', '다음 화~토 제안일에 확인')
        return None
    state = WorkerState.get(STATE) or {}
    existing = list(Proposal.objects.filter(candidate_key=key).order_by('id'))
    if (state.get('period') == key and state.get('room_sent_at')) or any(has_room_sent(p) for p in existing):
        _record(today, now, 'sent', '이 구간 검수방 알림 발송 완료')
        return None
    if not _rss_allows(today, posts, now):
        return None
    if existing:
        p = existing[0]
        preview = (p.extra or {}).get('editor_preview_at')
        _record(today, now, 'preview' if preview else 'generated',
                '관리자 미리보기, 검수방 미발송' if preview else '기존 질문 생성, 검수방 발송 대기',
                proposal_id=p.pk, rss_ok=True)
        return None
    waiting = _unanswered(now)
    if waiting:
        _record(today, now, 'waiting', '최근 14일 미답 질문 대기: 다음 제안일에 다시 확인',
                question_id=waiting.pk, rss_ok=True)
        return None
    materials = _materials(today, now, posts)
    try:
        questions, reason = _questions(llm, materials)
    except LLMError:
        _record(today, now, 'failed', '질문 생성 실패: 다음 제안일에 다시 확인', rss_ok=True)
        raise
    _record(today, now, 'ready', reason, rss_ok=True)
    draft = {'channel': Draft.EDITOR, 'title': '편집 일기 질문',
             'body': '\n'.join(f'{i}. {q}' for i, q in enumerate(questions, 1)),
             'extra': {'form': 'questions', 'period': key, 'questions': questions}}
    candidate = Candidate(id=key, kind='editor', books=[], summary=HEADLINE,
                          facts={'start': start.isoformat(), 'end': end.isoformat()}, urgency=3)
    return candidate, draft


def create_post(llm, question, text, actor):
    """원 질문에 답을 보존하고 이번 작성자의 답만 모아 새 글 판을 만든다."""
    if not is_question(question):
        raise ValueError('편집 일기 원 질문에 대한 답만 받을 수 있어요')
    if not text or is_acknowledgement(text):
        return None
    shown_question = question.body
    # 노션에서 질문 문구를 고친 사본도 답 저장 위치는 원 질문으로 유지한다.
    seen = {question.pk}
    while question.parent_id and question.parent_id not in seen:
        parent = question.parent
        if not is_question(parent) or parent.proposal_id != question.proposal_id:
            break
        question = parent
        seen.add(question.pk)
    actor = str(actor or '')[:100]
    note = CopyNote.objects.create(draft=question, text=text, by=actor)
    # 식별할 수 없는 작성자는 다른 미식별 답과 한 사람처럼 합치지 않는다.
    notes = list(question.notes.filter(by=actor).order_by('created_at', 'id')) if actor else [note]
    answers = [n.text for n in notes if not is_acknowledgement(n.text)]
    book = question.proposal.book
    book_data = {'title': book.title, 'subtitle': book.subtitle or ''} if book else {}
    payload = {'question': shown_question, 'author': actor, 'answers': answers, 'book': book_data}
    out = complete_json(llm, EDITOR_NOTE_SYSTEM, json.dumps(payload, ensure_ascii=False))
    title = fix_title_marks(out.get('title', '').strip()) if isinstance(out.get('title'), str) else ''
    body = fix_title_marks(out.get('body', '').strip()) if isinstance(out.get('body'), str) else ''
    source = '\n'.join(answers)
    if not body:
        raise LLMError('편집 일기 본문이 비어 있어요')
    if not valid_facts(f'{title}\n{body}', '\n'.join([source, *book_data.values()])):
        raise LLMError('자료에서 확인할 수 없는 숫자 또는 인용이 있어 편집 일기를 저장하지 않았어요')
    with transaction.atomic():
        # 같은 질문에 답이 이어져도 channel 내 version이 겹치지 않도록 제안을 잠근다.
        proposal = Proposal.objects.select_for_update().get(pk=question.proposal_id)
        version = (proposal.drafts.filter(channel=Draft.EDITOR).aggregate(n=Max('version'))['n'] or 0) + 1
        return Draft.objects.create(proposal=proposal, channel=Draft.EDITOR, title=title[:300], body=body,
                                    version=version, parent=question, origin=Draft.REWRITE,
                                    extra={'form': 'post', 'question_id': question.pk, 'author': actor,
                                           'answer_ids': [n.pk for n in notes], 'note': str(out.get('note') or '')[:600]})
