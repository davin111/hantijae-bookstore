"""노션 '전체 도서 데이터베이스'의 빈 칸만 채운다. 값이 있는 칸은 절대 덮어쓰지 않는다."""
import time

import requests

from intake.mapping import normalize_key

NOTION_VERSION = '2026-03-11'
API = 'https://api.notion.com/v1'


class NotionClient:
    def __init__(self, token, session=None):
        self.session = session or requests.Session()
        self.headers = {'Authorization': f'Bearer {token}', 'Notion-Version': NOTION_VERSION,
                        'Content-Type': 'application/json'}

    def _call(self, method, path, timeout=30, **kw):
        for attempt in range(2):
            res = self.session.request(method, f'{API}{path}', headers=self.headers, timeout=timeout, **kw)
            if getattr(res, 'status_code', 200) == 429 and attempt == 0:  # 요청이 몰리면 노션이 잠깐 기다리라고 한다
                time.sleep(min(float(res.headers.get('Retry-After') or 1), 5))
                continue
            res.raise_for_status()
            return res.json()

    def query_by_title(self, data_source_id, text):
        body = {'filter': {'property': '제목', 'title': {'contains': text}}, 'page_size': 50}
        return self._call('POST', f'/data_sources/{data_source_id}/query', json=body).get('results', [])

    def select_options(self, data_source_id, prop):
        schema = self._call('GET', f'/data_sources/{data_source_id}').get('properties', {})
        return [o['name'] for o in schema.get(prop, {}).get('select', {}).get('options', [])]

    def get_page(self, page_id):
        return self._call('GET', f'/pages/{page_id}')

    def update_page(self, page_id, properties):
        self._call('PATCH', f'/pages/{page_id}', json={'properties': properties})

    # ---- 읽기 전용(계기 잡기: context.notion 이 쓴다) ----
    def query_pages(self, data_source_id, published_after):
        """발행일이 published_after(YYYY-MM-DD) 이후이거나 비어 있는 페이지 전부(페이지 넘김 포함)."""
        body = {'page_size': 100, 'filter': {'or': [
            {'property': '발행일', 'date': {'on_or_after': published_after}},
            {'property': '발행일', 'date': {'is_empty': True}}]}}
        out = []
        while True:
            res = self._call('POST', f'/data_sources/{data_source_id}/query', json=body)
            out += res.get('results', [])
            if not res.get('has_more'):
                return out
            body['start_cursor'] = res['next_cursor']

    def children(self, block_id, timeout=30):
        """블록의 바로 아래 블록들(페이지 넘김 포함)."""
        out, cursor = [], None
        while True:
            params = {'page_size': 100, **({'start_cursor': cursor} if cursor else {})}
            res = self._call('GET', f'/blocks/{block_id}/children', timeout=timeout, params=params)
            out += res.get('results', [])
            if not res.get('has_more'):
                return out
            cursor = res['next_cursor']

    # ---- 쓰기(마케팅 '홍보 비서 글 모음': marketing.notion_sync 가 쓴다) ----
    def create_database(self, parent_page_id, title, properties):
        body = {'parent': {'type': 'page_id', 'page_id': parent_page_id},
                'title': [{'type': 'text', 'text': {'content': title}}],
                'initial_data_source': {'properties': properties}}
        return self._call('POST', '/databases', json=body)

    def create_page(self, data_source_id, properties, children=(), timeout=10):
        body = {'parent': {'type': 'data_source_id', 'data_source_id': data_source_id},
                'properties': properties, 'children': list(children)}
        return self._call('POST', '/pages', timeout=timeout, json=body)

    def append_children(self, block_id, children, timeout=10):
        return self._call('PATCH', f'/blocks/{block_id}/children', timeout=timeout,
                          json={'children': list(children)}).get('results', [])

    def update_block(self, block_id, payload):
        return self._call('PATCH', f'/blocks/{block_id}', timeout=10, json=payload)

    def trash_page(self, page_id):
        return self._call('PATCH', f'/pages/{page_id}', timeout=10, json={'in_trash': True})


def _title(page):
    return ''.join(t.get('plain_text', '') for t in page['properties'].get('제목', {}).get('title', []))


def _is_empty(prop):
    value = prop.get(prop.get('type'))
    return value in (None, [], '')


def _text(v):
    return {'rich_text': [{'type': 'text', 'text': {'content': v}}]}


def _match_row(rows, book_title):
    """(행, 'exact'|'prefix') 또는 (None, None). 노션엔 작업 제목(앞부분)만 적힌 행이 많아 유일한 접두 일치도 허용한다."""
    key = normalize_key(book_title)
    exact = [r for r in rows if normalize_key(_title(r)) == key]
    if len(exact) == 1:
        return exact[0], 'exact'
    prefix = [r for r in rows if normalize_key(_title(r)) and
              (key.startswith(normalize_key(_title(r))) or normalize_key(_title(r)).startswith(key))]
    return (prefix[0], 'prefix') if len(prefix) == 1 and not exact else (None, None)


def fill_notion_row(client, data_source_id, book, isbn_addon, site_url):
    first_word = book.title.split()[0].strip(',.') if book.title.split() else book.title
    rows = client.query_by_title(data_source_id, first_word)
    row, how = _match_row(rows, book.title)
    if row is None:
        return {'page_id': None, 'filled': [], 'note': f"노션에서 '{book.title}' 행을 하나로 특정하지 못했어요 ({len(rows)}개 후보)"}
    candidates = {
        '발행일': {'date': {'start': book.published_date.isoformat()}} if book.published_date else None,
        'ISBN': _text(book.isbn) if book.isbn else None,
        '부가기호': _text(isbn_addon) if isbn_addon else None,
        '가격': {'number': book.full_price} if book.full_price else None,
        '쪽수': {'number': book.page_count} if book.page_count else None,
        '부제': _text(book.subtitle) if book.subtitle else None,
        '온라인 책창고 링크': {'url': f'{site_url}/book={book.id}'},
    }
    if book.size and book.size in client.select_options(data_source_id, '판형'):
        candidates['판형'] = {'select': {'name': book.size}}
    props = {k: v for k, v in candidates.items()
             if v is not None and k in row['properties'] and _is_empty(row['properties'][k])}
    if props:
        client.update_page(row['id'], props)
    note = ''
    if how == 'prefix':
        note = (f"노션 '{_title(row)}' 행과 접두 일치로 매칭해 빈 칸({', '.join(sorted(props)) or '없음'})을 채웠어요 "
                f"— 다른 책이면 노션에서 되돌려 주세요")
    return {'page_id': row['id'], 'filled': sorted(props), 'note': note}
