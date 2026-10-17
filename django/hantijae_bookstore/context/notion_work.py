"""책에 연결된 업무 기록·할 일의 최신 내부 맥락. Notion에는 쓰지 않는다.

책 표의 명시적인 두 관계만 따라간다. 개별 업무는 하나의 안정적인 키로 저장하며,
대외 홍보 계기의 독립 근거로 쓰지 않는다(날짜·완료·계약 내용의 오해 방지).
"""
import re
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction

from context import notion as N
from context.models import ContextEntry

PREFIX = 'notion-work:'
SOURCES = (('업무 기록', 'work'), ('할 일', 'tasks'))
FIELDS = {'work': ('내용 요약', '날짜', '종류', '후속 조치'),
          'tasks': ('작업 이름', '상태', '마감일', '구분', '메모')}
ACTIVE = ('시작 전', '진행 중')
SCHEMA = {'work': {'내용 요약': 'title', '날짜': 'date', '종류': 'select', '후속 조치': 'rich_text'},
          'tasks': {'작업 이름': 'title', '상태': 'status', '마감일': 'date', '구분': 'select',
                    '메모': 'rich_text', '반복 업무': 'checkbox'}}


def internal(entry):
    return entry.source == ContextEntry.NOTION and entry.key.startswith(PREFIX)


def _id(value):
    return value.replace('-', '').lower()


def _day(value):
    return date.fromisoformat(value[:10]) if value else None


def _date_prop(props, name):
    return _day((props.get(name, {}).get('date') or {}).get('start'))


def _eligible(row, kind, cutoff):
    if row.get('archived') or row.get('in_trash'):
        return False
    props = row['properties']
    for name, expected in {**SCHEMA[kind], '관련 책': 'relation'}.items():
        if props.get(name, {}).get('type') != expected or expected not in props[name]:
            raise ValueError(f'업무 행의 {name} 속성을 읽지 못함')
    if kind == 'tasks':
        if N.prop_value(props.get('상태', {})) not in ACTIVE or props.get('반복 업무', {}).get('checkbox'):
            return False
        day = _date_prop(props, '마감일')
    else:
        day = _date_prop(props, '날짜')
    # 오래된 일을 최근 정리했다는 이유만으로 다시 들여오지 않는다.
    day = day or _day(row.get('created_time'))
    return day is not None and day >= cutoff


def _section(client, row, kind, books, now, sleep):
    prop = row['properties'].get('관련 책', {})
    if prop.get('type') != 'relation':
        raise ValueError('관련 책 연결 열이 없음')
    refs = client.relation_ids(row['id'], prop)
    sleep(N.PAUSE)
    for pid in refs:
        if _id(pid) in books:
            continue
        page = client.get_page(pid)
        sleep(N.PAUSE)
        if not (page.get('archived') or page.get('in_trash')):
            raise ValueError('관련 책이 책 표 조회에서 빠짐 — 위치·접근 확인 필요')
        books[_id(pid)] = ''
    titles = sorted({books[_id(pid)] for pid in refs if books[_id(pid)]})
    if not titles:
        return None
    top = []
    for b in N._children(client, row['id'], sleep):
        if b.get('type') in N.NO_DESCEND:
            continue
        sub = N._tree(client, b['id'], sleep) if b.get('has_children') else []
        top.append((b, sub))
    bodies = [s for s in N.sections(row, top) if s.text.strip()]
    props = row['properties']
    substantive = ('내용 요약', '후속 조치') if kind == 'work' else ('작업 이름', '메모')
    if not bodies and not any(N.prop_value(props.get(k, {})).strip() for k in substantive):
        return None
    names = ' / '.join(f'『{title}』' for title in titles)
    lines = [f'관련 책: {names}', '내부 업무 참고 — 마감일은 공개 행사일이 아닙니다.',
             f'노션 수정 시각: {row["last_edited_time"]}']
    lines += [f'{k}: {v}' for k in FIELDS[kind] if (v := N.prop_value(props.get(k, {})).strip())]
    lines += [f'{s.title}\n{s.text}' for s in bodies]
    key = f'{PREFIX}{kind}:{row["id"]}'
    # at은 마지막으로 확인한 시각. 실제 업무 날짜·노션 수정 시각은 본문에서 따로 보존한다.
    # 미완료 미래 업무/잊은 기록이 보관 만료 뒤 매일 되살아나는 것을 막는다.
    return N.Section(key, '업무 기록' if kind == 'work' else '할 일', '\n'.join(lines), now.isoformat()), names


def _targets(client, catalog, sleep):
    schema = client.data_source(catalog)
    sleep(N.PAUSE)
    targets = []
    for name, kind in SOURCES:
        prop = schema.get('properties', {}).get(name, {})
        ds = prop.get('relation', {}).get('data_source_id')
        if prop.get('type') != 'relation' or not ds:
            raise ValueError(f'{name} 관계형 표를 찾지 못함')
        target = client.data_source(ds)
        sleep(N.PAUSE)
        back = target.get('properties', {}).get('관련 책', {})
        if back.get('type') != 'relation' or _id(back.get('relation', {}).get('data_source_id', '')) != _id(catalog):
            raise ValueError(f'{name}의 관련 책이 기존 책 표를 가리키지 않음')
        for column, expected in SCHEMA[kind].items():
            if target.get('properties', {}).get(column, {}).get('type') != expected:
                raise ValueError(f'{name}의 {column} 열 이름·종류가 바뀜')
        targets.append((kind, ds))
    return targets


def sync_work(client, catalog, now, sleep):
    cutoff = (now - timedelta(days=settings.CONTEXT['RETENTION_DAYS'])).date()
    targets = _targets(client, catalog, sleep)
    books = {_id(p['id']): N.page_title(p) for p in client.query_all_pages(catalog)
             if N.page_title(p) and not p.get('archived') and not p.get('in_trash')}
    sleep(N.PAUSE)
    snapshots, inactive = [], set()
    # 모든 페이지·본문 조회가 끝나기 전에는 DB를 건드리지 않는다.
    for kind, ds in targets:
        prefix = f'{PREFIX}{kind}:'
        seen = set()
        rows = client.query_all_pages(ds)
        sleep(N.PAUSE)
        for row in rows:
            key = prefix + row['id']
            if key in seen:
                continue
            seen.add(key)
            section = _section(client, row, kind, books, now, sleep) if _eligible(row, kind, cutoff) else None
            if section:
                snapshots.append(section)
            else:
                inactive.add(key)
        # query에서 안 보이는 행은 삭제라고 단정하지 않는다(권한 문제일 수 있음).
        for key in ContextEntry.objects.filter(source=ContextEntry.NOTION, key__startswith=prefix).exclude(text='').values_list('key', flat=True):
            if key in seen:
                continue
            page = client.get_page(key[len(prefix):])
            sleep(N.PAUSE)
            if page.get('archived') or page.get('in_trash'):
                inactive.add(key)
            else:
                raise ValueError('기존 업무가 표 조회에서 빠짐 — 위치·접근 확인 필요')
    changed = 0
    with transaction.atomic():
        for section, names in snapshots:
            # _upsert의 책 제목 감싸기는 하나의 표시 형식에만 사용한다.
            changed += N._upsert(section, names.removeprefix('『').removesuffix('』'), now)
        changed += ContextEntry.objects.filter(key__in=inactive, forgotten=False).exclude(text='').update(
            text='', heading='', redactions={}, edited_at=now, at=now)
    return changed


def context_for(entries, now, limit=10):
    """같은 책을 다루는 새 입력에만 최근 확인한 업무를 참고로 붙인다."""
    from unicodedata import normalize
    def normalized(s):
        return re.sub(r'[\W_]+', '', normalize('NFC', s))
    text = normalized('\n'.join(' '.join([e.heading, e.text, e.media_text]) for e in entries))
    out = []
    candidates = ContextEntry.objects.filter(source=ContextEntry.NOTION, key__startswith=PREFIX,
                                             forgotten=False, at__gte=now - timedelta(days=2), at__lte=now).exclude(text='')
    for e in candidates.order_by('-at', '-id'):
        names = re.findall(r'『([^』]+)』', N.unmark(e.text).split('\n', 1)[0])
        if any(len(normalized(name)) >= 3 and normalized(name) in text for name in names):
            out.append(e)
            if len(out) >= limit:
                break
    return out
