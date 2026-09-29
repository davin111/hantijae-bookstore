"""계기 잡기: 가린 기록(운영진 대화·사진에서 옮겨 적은 글·노션 책 페이지 구역)에서 LLM이 '책을 지금 알릴 계기'를
뽑고, 코드가 다시 검증해 Signal(kind=moment)로 둔다. 스펙 .claude/docs/specs/2026-09-30-context-moments-design.md §7.

흐름: pending_entries(아직 안 본 기록) → chunks(3만 자씩) → LLM(MOMENT_SYSTEM) → validate(근거·숫자·날짜·중복)
→ apply(저장) → MomentScan(본 기록 표시). LLM은 요약과 근거 번호만 내고, 원문은 결과에 옮기지 않는다.
"""
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List

from django.db import transaction
from django.db.models import Count, Q

from books.models import Book
from context.models import ContextEntry
from context.redact import redact
from intake.llm import Attachment, complete_json
from marketing.moment_dates import date_supported
from marketing.models import MomentScan, Proposal, Signal, SignalEvidence
from marketing.prompts import MOMENT_SYSTEM, build_moment_user
from marketing.text import clip, foreign_numbers, title_key
from marketing.timeutil import KST, kst_today

log = logging.getLogger('intake')
TYPES = ('author', 'event', 'group', 'selection', 'funding', 'media', 'issue', 'stock', 'upcoming')
TYPE_LABEL = {'author': '저자 활동', 'event': '행사', 'group': '단체', 'selection': '선정·수상', 'funding': '펀딩',
              'media': '매체 소개', 'issue': '시사', 'stock': '책 상태·수요', 'upcoming': '신간 예고'}
STATUSES = ('planned', 'confirmed', 'done', 'cancelled')
CHUNK_CHARS, MAX_CHUNKS, CONTEXT_LINES, OPEN_LIMIT, PAST_DAYS = 30000, 4, 30, 40, 7
WEEKDAYS = '월화수목금토일'
MEDIA_LABEL = {'video': '동영상', 'voice': '음성', 'audio': '오디오', 'sticker': '스티커', 'animation': '움짤',
               'video_note': '영상 메시지', 'contact': '연락처', 'location': '위치', 'poll': '투표'}
DIGEST_LIMIT = 4096


@dataclass
class Report:
    new: List[Signal] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)
    preview: List[str] = field(default_factory=list)  # dry-run 에서 저장하지 않고 보여 줄 줄
    errors: List[str] = field(default_factory=list)
    photos: int = 0
    notion: int = 0
    swept: int = 0
    left: int = 0  # 이번에 못 넣어 다음으로 넘긴 기록 수


# ---- 입력 고르기와 글 만들기 ----
def pending_entries():
    """아직 추출에 넣지 않았거나, 넣은 뒤 바뀐(수정·사진 읽음) 기록. at 순서."""
    seen = dict(MomentScan.objects.values_list('entry_id', 'changed_at'))
    return [e for e in ContextEntry.objects.filter(forgotten=False).order_by('at', 'id')
            if e.id not in seen or e.changed_at > seen[e.id]]


def _meaningful(e):
    return bool(e.text.strip() or e.media_text.strip())


def _waiting_photo(e):
    """아직 읽지 않은 사진: 읽힌 뒤 다시 '바뀐 기록'이 되니 지금 표시하지 않는다."""
    return e.is_image and bool(e.file_id) and e.media_read_at is None


def _when(e):
    t = e.at.astimezone(KST)
    return f'{t.month}/{t.day}({WEEKDAYS[t.weekday()]}) {t:%H:%M}'


def _media_part(e):
    if e.is_image:
        if e.media_text:
            return f'[사진] {e.media_text}'
        return '[사진, 아직 못 읽음]' if _waiting_photo(e) else '[사진]'
    if e.media == 'document':
        return f'[파일: {e.media_name}]' if e.media_name else '[파일]'
    return f'[{MEDIA_LABEL.get(e.media, e.media)}]' if e.media else ''


def line(e, reply_ids=None):
    """기록 한 줄. #번호는 ContextEntry 번호(= LLM이 근거로 적을 번호)."""
    if e.source == ContextEntry.NOTION:
        t = e.at.astimezone(KST)
        return f'[#{e.id} 노션 · {e.heading} · {t.month}/{t.day} 수정]\n{e.text}'
    body = ' '.join(p for p in (_media_part(e), e.text.strip()) if p)
    tail = ''
    if e.reply_to_id:
        target = (reply_ids or {}).get((e.chat_id, e.origin, e.reply_to_id))
        tail += f' (↩#{target})' if target else (' (↩봇)' if e.reply_to_bot else ' (↩답장)')
    if e.forwarded:
        tail += ' (전달)'
    return f'[#{e.id} {_when(e)} {e.role}] {body}{tail}'


def chunks(entries, limit=None):
    """at 순서의 기록을 limit자 안팎으로 나눈다(한 줄이 limit보다 길면 그 줄 혼자 한 조각)."""
    limit = limit or CHUNK_CHARS
    out, cur, size = [], [], 0
    for e in entries:
        n = len(line(e)) + 1
        if cur and size + n > limit:
            out.append(cur)
            cur, size = [], 0
        cur.append(e)
        size += n
    if cur:
        out.append(cur)
    return out


def context_before(chunk):
    """조각의 첫 텔레그램 기록 앞 30줄(같은 방). 답장과 흐름을 이해하게 하는 참고용."""
    first = next((e for e in chunk if e.source == ContextEntry.TELEGRAM), None)
    if first is None:
        return []
    qs = (ContextEntry.objects.filter(source=ContextEntry.TELEGRAM, chat_id=first.chat_id, forgotten=False,
                                      at__lte=first.at)
          .exclude(id__in=[e.id for e in chunk]).order_by('-at', '-id')[:CONTEXT_LINES])
    return list(reversed(qs))


def books_block():
    lines = []
    for b in Book.objects.prefetch_related('authors__author').order_by('-published_date', 'id'):
        names = ', '.join(a.author.name for a in b.authors.all())
        lines.append(f'『{b.title}』' + (f' — {names}' if names else ''))
    return '\n'.join(lines)


def book_index():
    return {title_key(b.title): b for b in Book.objects.all()}


def find_book(title, index=None):
    """LLM이 적은 제목 → Book. 『』·공백은 무시하고, '제목 ― 부제'·'제목: 부제'면 앞부분으로도 찾는다."""
    index = book_index() if index is None else index
    raw = str(title or '').strip()
    for cand in (raw, re.split(r'\s*[―—:]\s*', raw)[0]):
        b = index.get(title_key(cand))
        if b:
            return b
    return None


def open_moments(today, now, limit=OPEN_LIMIT):
    """LLM에 '이미 아는 계기'로 보여 줄 것: 취소 아님, 날짜가 7일 전 이후이거나 날짜 없이 30일 안에 찾은 것."""
    out = []
    for s in Signal.objects.filter(kind=Signal.MOMENT).select_related('book').order_by('-found_at', '-id'):
        if s.detail.get('status') == 'cancelled':
            continue
        if s.happens_on and s.happens_on < today - timedelta(days=PAST_DAYS):
            continue
        if not s.happens_on and s.found_at < now - timedelta(days=30):
            continue
        out.append(s)
        if len(out) == limit:
            break
    return out


def book_label(s):
    if s.book:
        return f'『{s.book.title}』'
    hint = s.detail.get('book_hint')
    return f'『{hint}』?' if hint else '(책 없음)'


def _when_label(day, d):
    if day:
        return f'{day.month}/{day.day}'
    return d.get('date_text') or '날짜 없음'


def open_line(s):
    d = s.detail
    return (f'#{s.id} [{d.get("type")}/{d.get("status")}] {_when_label(s.happens_on, d)} {book_label(s)} '
            f'{s.title} — {d.get("summary", "")}')


# ---- 검증 ----
def _clean(value, limit):
    return redact(str(value or '').strip())[0][:limit]


def _parse_date(value):
    try:
        return date.fromisoformat(str(value or '').strip()[:10])
    except ValueError:
        return None


def _ids(values):
    out = []
    for v in values if isinstance(values, list) else []:
        try:
            out.append(int(str(v).strip().lstrip('#')))
        except ValueError:
            continue
    return out


def _pick(values, by_id):
    out = []
    for i in _ids(values):
        e = by_id.get(i)
        if e is not None and e not in out:
            out.append(e)
    return out


def _local_day(e):
    return e.at.astimezone(KST).date()


def _date_evidence(entries):
    return [(' '.join([e.heading, e.text, e.media_text]), _local_day(e)) for e in entries]


def _allowed(entries, today, day):
    """지어낸 숫자 검사의 허용 자료: 근거 글 + 근거 날짜·오늘·확인된 날짜(요약의 ISO 날짜 '2026-…'이 걸리지 않게)."""
    texts = [today.isoformat()] + ([day.isoformat()] if day else [])
    for e in entries:
        texts += [e.text, e.media_text, e.heading, _local_day(e).isoformat()]
    return texts


def _check_date(value, date_text, entries):
    """(확인된 날짜 또는 None, 날짜 글, 확인 못 함 여부)."""
    text = _clean(date_text, 50)
    day = _parse_date(value)
    if day is None:
        return None, text, False
    if date_supported(day, _date_evidence(entries)):
        return day, text, False
    return None, text or day.isoformat(), True


def _books(titles, index):
    found, hint = [], ''
    for t in titles if isinstance(titles, list) else []:
        b = find_book(t, index)
        if b and b not in found:
            found.append(b)
        elif not b and not hint and str(t).strip():
            hint = _clean(t, 100).strip('『』 ')
    return found[:3], hint


def _new(raw, by_id, index, today):
    """(fields, 근거 기록들, 버린 이유)."""
    kind, status = raw.get('type'), raw.get('status') or 'planned'
    title = _clean(raw.get('title'), 80)
    if kind not in TYPES or status not in STATUSES:
        return None, [], f'{title or "(제목 없음)"}: 모르는 종류·상태 {kind}/{status}'
    ev = _pick(raw.get('evidence'), by_id)
    if not ev:
        return None, [], f'{title or "(제목 없음)"}: 근거 없음'
    if not title:
        return None, [], f'빈 제목 (#{ev[0].id})'
    summary, place = _clean(raw.get('summary'), 300), _clean(raw.get('place'), 100)
    day, date_text, unverified = _check_date(raw.get('date'), raw.get('date_text'), ev)
    if day and day < today - timedelta(days=PAST_DAYS):
        return None, [], f'{title}: 지난 일({day.isoformat()})'
    bad = foreign_numbers(' '.join([title, summary, place]), _allowed(ev, today, day))
    if bad:
        return None, [], f'{title}: 자료에 없는 숫자 {", ".join(bad)}'
    books, hint = _books(raw.get('books'), index)
    return {'type': kind, 'status': status, 'title': title, 'summary': summary, 'place': place, 'happens_on': day,
            'date_text': date_text, 'date_unverified': unverified, 'books': books, 'book_hint': hint,
            'promoted': raw.get('promoted') is True, 'sensitive': raw.get('sensitive') is True}, ev, ''


def _same(opens, f):
    """열린 계기 가운데 같은 일(같은 종류 + 같은 대표 책 + 날짜 ±1일, 둘 다 날짜 없으면 제목 열쇠 같음)."""
    if not f['books']:
        return None
    book_id = f['books'][0].id
    for s in opens:
        if s.detail.get('type') != f['type'] or s.book_id != book_id:
            continue
        if s.happens_on and f['happens_on'] and abs((s.happens_on - f['happens_on']).days) <= 1:
            return s
        if not s.happens_on and not f['happens_on'] and title_key(s.title) == title_key(f['title']):
            return s
    return None


def _evidence_of(s):
    return [x.entry for x in s.evidence.select_related('entry')]


def _merge_changes(s, f):
    """새 계기로 들어왔지만 열린 계기와 같은 일일 때 바꿀 칸(날짜는 ±1일 안이라 그대로 둔다)."""
    changes = {}
    if f['status'] != s.detail.get('status'):
        changes['status'] = f['status']
    for key in ('summary', 'place'):
        if f[key] and f[key] != s.detail.get(key):
            changes[key] = f[key]
    if f['promoted'] and not s.detail.get('promoted'):
        changes['promoted'] = True
    return changes


def _update(raw, by_id, open_by_id, today):
    """(action 또는 None, 버린 이유). 바뀐 게 없으면 (None, '')."""
    ids = _ids([raw.get('id')])
    s = open_by_id.get(ids[0]) if ids else None
    if s is None:
        return None, f'없는 계기 번호: {raw.get("id")}'
    status = raw.get('status') or ''
    if status and status not in STATUSES:
        return None, f'#{s.id}: 모르는 상태 {status}'
    old = _evidence_of(s)
    added = [e for e in _pick(raw.get('evidence'), by_id) if e not in old]
    every = old + added
    changes = {}
    if status and status != s.detail.get('status'):
        changes['status'] = status
    for key, limit in (('summary', 300), ('place', 100)):
        v = _clean(raw.get(key), limit)
        if v and v != s.detail.get(key):
            changes[key] = v
    if raw.get('promoted') is True and not s.detail.get('promoted'):
        changes['promoted'] = True
    if raw.get('date'):
        day, text, unverified = _check_date(raw.get('date'), raw.get('date_text'), every)
        if day and day != s.happens_on:
            changes.update(happens_on=day, date_text=text, date_unverified=False)
        elif unverified and not s.happens_on:  # 확인된 날짜를 확인 못 한 날짜로 덮지 않는다
            changes.update(date_text=text, date_unverified=True)
    bad = foreign_numbers(' '.join([changes.get('summary', ''), changes.get('place', '')]),
                          _allowed(every, today, changes.get('happens_on') or s.happens_on))
    if bad:
        return None, f'#{s.id}: 자료에 없는 숫자 {", ".join(bad)}'
    if not changes and not added:
        return None, ''
    return {'op': 'update', 'signal': s, 'changes': changes, 'evidence': added}, ''


def validate(raw, by_id, open_by_id, index, today):
    """LLM 응답 → (저장할 동작 목록, 버린 이유 목록)."""
    actions, dropped = [], []
    raw = raw if isinstance(raw, dict) else {}
    for item in raw.get('new') or []:
        if not isinstance(item, dict):
            continue
        f, ev, reason = _new(item, by_id, index, today)
        if f is None:
            dropped.append(reason)
            continue
        same = _same(list(open_by_id.values()), f)
        if same:
            old = _evidence_of(same)
            actions.append({'op': 'update', 'signal': same, 'changes': _merge_changes(same, f),
                            'evidence': [e for e in ev if e not in old]})
        else:
            actions.append({'op': 'new', 'fields': f, 'evidence': ev})
    for item in raw.get('updates') or []:
        if not isinstance(item, dict):
            continue
        action, reason = _update(item, by_id, open_by_id, today)
        if action:
            actions.append(action)
        elif reason:
            dropped.append(reason)
    return actions, dropped


# ---- 저장 ----
def _link(s, entries):
    SignalEvidence.objects.bulk_create([SignalEvidence(signal=s, entry=e) for e in entries], ignore_conflicts=True)


def _create(f, entries):
    detail = {'type': f['type'], 'status': f['status'], 'summary': f['summary'], 'place': f['place'],
              'date_text': f['date_text'], 'date_unverified': f['date_unverified'],
              'book_ids': [b.id for b in f['books']], 'book_hint': f['book_hint'], 'promoted': f['promoted'],
              'sources': sorted({e.source for e in entries})}
    s = Signal.objects.create(kind=Signal.MOMENT, key=f'moment:{uuid.uuid4().hex[:16]}',
                              book=f['books'][0] if f['books'] else None, title=f['title'], detail=detail,
                              happens_on=f['happens_on'], relevant=f['status'] != 'cancelled',
                              sensitive=f['sensitive'])
    _link(s, entries)
    return s


def _describe(s, changes, added):
    parts = []
    if 'happens_on' in changes:
        before = f'{s.happens_on.month}/{s.happens_on.day}' if s.happens_on else '없음'
        after = changes['happens_on']
        after = f'{after.month}/{after.day}' if after else '없음'
        parts.append(f'날짜 {before} → {after}')
    if 'status' in changes:
        parts.append({'cancelled': '취소', 'done': '끝남', 'confirmed': '확정', 'planned': '예정'}[changes['status']])
    if changes.get('promoted'):
        parts.append('이미 올림')
    if 'summary' in changes or 'place' in changes:
        parts.append('내용 보탬')
    if added:
        parts.append(f'근거 +{added}')
    return f'{book_label(s)} {s.title}: ' + ' · '.join(parts or ['근거 +0'])


def _save_update(s, changes, entries):
    desc = _describe(s, changes, len(entries))
    detail = dict(s.detail)
    for key in ('status', 'summary', 'place', 'date_text', 'date_unverified', 'promoted'):
        if key in changes:
            detail[key] = changes[key]
    detail['sources'] = sorted(set(detail.get('sources', [])) | {e.source for e in entries})
    if 'happens_on' in changes:
        s.happens_on = changes['happens_on']
    s.detail = detail
    s.relevant = detail.get('status') != 'cancelled'
    s.save(update_fields=['detail', 'happens_on', 'relevant'])
    _link(s, entries)
    return desc


def apply(actions, report):
    for a in actions:
        if a['op'] == 'new':
            report.new.append(_create(a['fields'], a['evidence']))
        elif a['changes'] or a['evidence']:
            report.changed.append(_save_update(a['signal'], a['changes'], a['evidence']))


def _mark(entries):
    for e in entries:
        MomentScan.objects.update_or_create(entry_id=e.id, defaults={'changed_at': e.changed_at})


def _refs(entries):
    return ' '.join(f'#{e.id}' for e in entries)


def preview_line(a):
    if a['op'] == 'new':
        f = a['fields']
        when = f['happens_on'].isoformat() if f['happens_on'] else (f['date_text'] or '날짜 없음')
        if f['date_unverified']:
            when += '(확인 못 함)'
        books = ', '.join(f'『{b.title}』' for b in f['books']) or (f'『{f["book_hint"]}』?' if f['book_hint'] else '책 없음')
        flag = ' 🔕' if f['sensitive'] else ''
        return (f'+ [{f["type"]}/{f["status"]}] {when} {books} {f["title"]} — {f["summary"]} '
                f'({_refs(a["evidence"])}){flag}')
    return '~ ' + _describe(a['signal'], a['changes'], len(a['evidence']))


def run(llm, now, report=None, entries=None, max_chunks=MAX_CHUNKS, dry_run=False):
    """새 기록에서 계기를 뽑아 저장한다. 조각 하나가 실패하면 거기서 멈추고, 앞 조각까지만 저장·표시한다."""
    report = report or Report()
    today = kst_today(now)
    entries = pending_entries() if entries is None else entries
    work = [e for e in entries if _meaningful(e)]
    if not dry_run:  # 스티커·빈 기록은 LLM 없이 본 것으로(읽기를 기다리는 사진만 빼고)
        _mark([e for e in entries if not _meaningful(e) and not _waiting_photo(e)])
    if not work:
        return report
    parts = chunks(work)
    report.left = sum(len(c) for c in parts[max_chunks:])
    index, books_text = book_index(), books_block()
    for chunk in parts[:max_chunks]:
        context = context_before(chunk)
        opens = open_moments(today, now)
        shown = context + chunk
        reply_ids = {(e.chat_id, e.origin, e.message_id): e.id for e in shown if e.message_id is not None}
        user = build_moment_user(today, books_text, [open_line(s) for s in opens],
                                 '\n'.join(line(e, reply_ids) for e in context),
                                 '\n'.join(line(e, reply_ids) for e in chunk))
        try:
            raw = complete_json(llm, MOMENT_SYSTEM, user)
        except Exception as e:
            log.exception('moment extraction failed')
            report.errors.append(f'추출 중단: {type(e).__name__}: {e}')
            report.left += len(chunk)
            break
        actions, dropped = validate(raw, {e.id: e for e in shown}, {s.id: s for s in opens}, index, today)
        report.dropped += dropped
        if dry_run:
            report.preview += [preview_line(a) for a in actions]
            continue
        with transaction.atomic():
            apply(actions, report)
            _mark(chunk)
    return report


# ---- 정리(/잊어·90일) ----
def _drop(signals):
    """계기와, 그 계기를 쓴 아직 안 보낸 제안(초안 포함)을 지운다. 보낸 제안은 signal 연결만 끊긴다(SET_NULL)."""
    ids = [s.id for s in signals]
    if not ids:
        return 0
    Proposal.objects.filter(signal_id__in=ids).filter(
        Q(kind=Proposal.NOW, sent_at__isnull=True)
        | Q(kind=Proposal.BRIEF_ITEM, briefing__sent_at__isnull=True)).delete()
    Signal.objects.filter(id__in=ids).delete()
    return len(ids)


def sweep():
    """근거 가운데 하나라도 잊은 기록이 있거나, 근거가 모두 정리돼 없는 계기를 지운다."""
    forgotten = Signal.objects.filter(kind=Signal.MOMENT, evidence__entry__forgotten=True)
    empty = Signal.objects.filter(kind=Signal.MOMENT).annotate(n=Count('evidence')).filter(n=0)
    return _drop(set(forgotten) | set(empty))


def drop_for_entries(entry_ids):
    """/잊어 직후: 그 기록을 근거로 한 계기를 바로 지운다."""
    if not entry_ids:
        return 0
    return _drop(set(Signal.objects.filter(kind=Signal.MOMENT, evidence__entry_id__in=list(entry_ids))))


# ---- 관리자 요약 ----
def signal_line(s):
    d = s.detail
    ids = ' '.join(f'#{i}' for i in s.evidence.values_list('entry_id', flat=True))
    return f'{book_label(s)} {_when_label(s.happens_on, d)} {TYPE_LABEL.get(d.get("type"), "계기")} — {s.title} ({ids})'


def digest(report, now):
    """바뀐 게 있을 때만 관리자 1:1 방에 보낼 한 메시지. 없으면 빈 문자열."""
    if not (report.new or report.changed or report.dropped or report.errors or report.swept):
        return ''
    t = now.astimezone(KST)
    lines = [f'🔎 대화 속 계기 ({t.month}/{t.day} {t:%H:%M})',
             f'새로 {len(report.new)} · 바뀜 {len(report.changed)} · 버림 {len(report.dropped)}'
             + (f' · 지움 {report.swept}' if report.swept else '')]
    calm = [s for s in report.new if not s.sensitive]
    lines += ['+ ' + signal_line(s) for s in calm]
    lines += ['~ ' + c for c in report.changed]
    lines += ['- 버림: ' + d for d in report.dropped]
    lines += [f'? {book_label(s)} {s.title}: 날짜 확인 못 함 "{s.detail.get("date_text", "")}"'
              for s in calm if s.detail.get('date_unverified')]
    hot = [s for s in report.new if s.sensitive]
    if hot:
        lines.append(f'🔕 민감 {len(hot)}건 — 홍보를 쉬려면 /quiet 줄의 날짜·이유를 채워 보내세요')
        for s in hot:
            lines.append(f'· {book_label(s)} {s.title}' + (f'\n  /quiet {s.book.title[:12]} YYYY-MM-DD 이유' if s.book else ''))
    lines.append(f'사진 {report.photos}장 · 노션 구역 {report.notion}개'
                 + (f' · 남은 기록 {report.left}줄은 다음에' if report.left else ''))
    lines += [f'⚠️ {e}' for e in report.errors]
    return clip('\n'.join(lines), DIGEST_LIMIT)


# ---- 사진 읽기 연결 ----
def photo_ask(llm):
    """context.photos.read_pending 에 넘길 LLM 호출(사진은 image/jpeg 첨부로)."""
    def ask(system, user, images):
        return complete_json(llm, system, user,
                             [Attachment('image', 'image/jpeg', data, f'{i}.jpg') for i, data in enumerate(images, 1)])
    return ask
