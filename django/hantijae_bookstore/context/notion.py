"""노션 카탈로그 책 페이지(속성 + 본문)를 구역으로 나눠 기록(ContextEntry, source=notion)에 넣는다. 읽기만 한다.

구역: 속성 전체 한 구역, 맨 위 토글 하나(안쪽 전체) 한 구역, 토글이 아닌 블록은 바로 앞 제목 구역에(첫 제목 앞은 '머리').
구역 단위인 이유: 계기의 근거가 '이 페이지 어딘가'가 아니라 '12/17 통화'를 가리키고, 바뀐 구역만 다시 추출에 가게.
매일 대상 페이지 전체를 훑고 내용을 비교한다(페이지 수정 시각은 속성 편집으로도 움직여 믿기 어렵다 — 2026-09-30 시험).
노션 클라이언트(query_pages, children)는 부르는 쪽이 넘긴다 — context 는 intake 를 import 하지 않는다.
"""
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings

from context.models import ContextEntry
from context.redact import redact

PAUSE = 0.35  # 노션 API 한도 초당 3회
KEEP = 20000
TEXT_TYPES = ('paragraph', 'heading_1', 'heading_2', 'heading_3', 'bulleted_list_item', 'numbered_list_item', 'to_do',
              'toggle', 'quote', 'callout', 'code')
CONTAINER_TYPES = ('table', 'column_list', 'column', 'synced_block')  # 글은 안쪽 블록이 가진다
NO_DESCEND = ('child_page', 'child_database')
CHANGED = '★ '  # 다시 읽었을 때 새로 생기거나 바뀐 줄 표시(추출 LLM이 새 부분을 알아보게)


@dataclass
class Section:
    key: str
    title: str
    text: str
    at: str  # ISO 문자열(노션 형식이 같아 문자열로 비교 가능)


def plain(rich):
    return ''.join(t.get('plain_text', '') for t in rich or [])


def block_text(b):
    kind = b.get('type', '')
    v = b.get(kind) or {}
    if kind in TEXT_TYPES:
        text = plain(v.get('rich_text'))
        return (('[x] ' if v.get('checked') else '[ ] ') + text) if kind == 'to_do' else text
    if kind == 'table_row':
        return ' | '.join(plain(cell) for cell in v.get('cells', []))
    if kind in CONTAINER_TYPES:
        return ''
    return f'[{kind}]'


def is_toggle(b):
    kind = b.get('type', '')
    return kind == 'toggle' or (kind.startswith('heading_') and (b.get(kind) or {}).get('is_toggleable'))


def _join(lines):
    return '\n'.join(line for line in lines if line.strip())


def sections(page, top):
    """top: [(맨 위 블록, [(깊이, 안쪽 블록), ...]), ...] → 본문 구역들(빈 구역은 뺀다)."""
    out, current = [], None
    for b, sub in top:
        inner = ['  ' * depth + block_text(x) for depth, x in sub]
        latest = max([b['last_edited_time']] + [x['last_edited_time'] for _, x in sub])
        if is_toggle(b):  # 토글은 따로 한 구역. 그 뒤 블록은 앞 제목 구역에 계속 붙는다(구역 키가 겹치지 않게)
            out.append(Section(f'notion:{b["id"]}', block_text(b), _join(inner), latest))
            continue
        if b.get('type', '').startswith('heading_'):
            current = Section(f'notion:{b["id"]}', block_text(b), _join(inner), latest)
            out.append(current)
            continue
        if current is None:
            current = Section(f'notion:{page["id"]}:top', '머리', '', latest)
            out.append(current)
        current.text = _join([current.text, block_text(b), *inner])
        current.at = max(current.at, latest)
    return [s for s in out if s.text.strip()]


def prop_value(p):
    kind = p.get('type')
    v = p.get(kind)
    if kind in ('title', 'rich_text'):
        return plain(v)
    if kind == 'date':
        return '' if not v else v.get('start', '') + (f' ~ {v["end"]}' if v.get('end') else '')
    if kind in ('select', 'status'):
        return (v or {}).get('name', '')
    if kind == 'multi_select':
        return ', '.join(o.get('name', '') for o in v or [])
    if kind == 'checkbox':
        return '예' if v else ''
    if kind == 'number':
        return '' if v is None else str(v)
    if kind == 'url':
        return v or ''
    return ''  # relation·files·people 등은 글로 옮기지 않는다


def page_title(page):
    for p in page.get('properties', {}).values():
        if p.get('type') == 'title':
            return plain(p.get('title'))
    return ''


def props_section(page):
    lines = [f'{name}: {value}' for name, p in page.get('properties', {}).items()
             if name.strip() and (value := prop_value(p).strip())]
    if not lines:
        return None
    return Section(f'notion:{page["id"]}:props', '속성', '\n'.join(lines), page['last_edited_time'])


def _parse(ts):
    return datetime.fromisoformat(ts.replace('Z', '+00:00'))


def _children(client, block_id, sleep):
    blocks = client.children(block_id)
    sleep(PAUSE)
    return blocks


def _tree(client, block_id, sleep, depth=1):
    out = []
    for b in _children(client, block_id, sleep):
        out.append((depth, b))
        if b.get('has_children') and b.get('type') not in NO_DESCEND:
            out += _tree(client, b['id'], sleep, depth + 1)
    return out


def unmark(text):
    return '\n'.join(line[len(CHANGED):] if line.startswith(CHANGED) else line for line in (text or '').split('\n'))


def _mark_changes(old, new):
    """이전 글에 없던 줄 앞에 ★. 무엇이 바뀌었는지 LLM이 알아야 옛 값으로 계기를 다시 만들지 않는다."""
    before = set(old.split('\n'))
    return '\n'.join(CHANGED + line if line.strip() and line not in before else line for line in new.split('\n'))


def _upsert(sec, title, now):
    text, counts = redact(sec.text)  # 가린 뒤 자른다(잘린 자리의 전화번호가 가림을 피하지 않게)
    text = text[:KEEP]
    heading = redact(f'『{title}』 · {sec.title}')[0][:200]
    at = _parse(sec.at)
    entry = ContextEntry.objects.filter(key=sec.key).first()
    if entry is None:
        ContextEntry.objects.create(key=sec.key, source=ContextEntry.NOTION, origin=ContextEntry.LIVE, at=at,
                                    heading=heading, text=text, redactions=counts)
        return 1
    old = unmark(entry.text)
    if entry.forgotten or (old == text and entry.heading == heading):
        # 내용은 그대로 두고 시각만 따라간다 — 잊은 구역이 90일 정리로 지워졌다가 다음 훑기에 되살아나지 않게,
        # 안 바뀐 구역이 90일마다 새 기록으로 다시 추출에 가지 않게(edited_at 은 건드리지 않는다)
        if at > entry.at:
            ContextEntry.objects.filter(pk=entry.pk).update(at=at)
        return 0
    text = _mark_changes(old, text)
    entry.text, entry.heading, entry.redactions, entry.at, entry.edited_at = text, heading, counts, at, now
    entry.save(update_fields=['text', 'heading', 'redactions', 'at', 'edited_at', 'updated_at'])
    return 1


def sync(client, data_source_id, now, sleep=time.sleep):
    """대상 책 페이지(발행일 1년 안 또는 비어 있음)를 훑어 새로 넣거나 바뀐 구역 수를 돌려준다.
    보관 일수(90일)보다 오래 안 고친 구역은 넣지 않는다 — 정리했다가 다시 넣는 반복을 막는다."""
    cutoff = now - timedelta(days=settings.CONTEXT['RETENTION_DAYS'])
    published_after = (now.date() - timedelta(days=365)).isoformat()
    changed, failed = 0, []
    for page in client.query_pages(data_source_id, published_after):
        sleep(PAUSE)
        try:  # 페이지 하나의 오류가 그 뒤 페이지를 막지 않게
            changed += _sync_page(client, page, cutoff, now, sleep)
        except Exception as e:
            failed.append(f'{page_title(page) or page.get("id")}: {type(e).__name__}: {e}')
    if failed:
        raise RuntimeError(f'노션 페이지 {len(failed)}개 읽기 실패(나머지 {changed}구역은 반영) — {failed[0]}')
    return changed


def _sync_page(client, page, cutoff, now, sleep):
    top = []
    for b in _children(client, page['id'], sleep):
        sub = _tree(client, b['id'], sleep) if b.get('has_children') and b.get('type') not in NO_DESCEND else []
        top.append((b, sub))
    title, changed = page_title(page), 0
    for sec in [props_section(page)] + sections(page, top):
        if sec is None or _parse(sec.at) < cutoff:
            continue
        changed += _upsert(sec, title, now)
    return changed
