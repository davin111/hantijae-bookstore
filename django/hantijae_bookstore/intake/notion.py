"""노션 '전체 도서 데이터베이스'의 빈 칸만 채운다. 값이 있는 칸은 절대 덮어쓰지 않는다."""
import requests

from intake.mapping import normalize_key

NOTION_VERSION = '2026-03-11'
API = 'https://api.notion.com/v1'


class NotionClient:
    def __init__(self, token, session=None):
        self.session = session or requests.Session()
        self.headers = {'Authorization': f'Bearer {token}', 'Notion-Version': NOTION_VERSION,
                        'Content-Type': 'application/json'}

    def _call(self, method, path, **kw):
        res = self.session.request(method, f'{API}{path}', headers=self.headers, timeout=30, **kw)
        res.raise_for_status()
        return res.json()

    def query_by_title(self, data_source_id, text):
        body = {'filter': {'property': '제목', 'title': {'contains': text}}, 'page_size': 50}
        return self._call('POST', f'/data_sources/{data_source_id}/query', json=body).get('results', [])

    def select_options(self, data_source_id, prop):
        schema = self._call('GET', f'/data_sources/{data_source_id}').get('properties', {})
        return [o['name'] for o in schema.get(prop, {}).get('select', {}).get('options', [])]

    def update_page(self, page_id, properties):
        self._call('PATCH', f'/pages/{page_id}', json={'properties': properties})


def _title(page):
    return ''.join(t.get('plain_text', '') for t in page['properties'].get('제목', {}).get('title', []))


def _is_empty(prop):
    value = prop.get(prop.get('type'))
    return value in (None, [], '')


def _text(v):
    return {'rich_text': [{'type': 'text', 'text': {'content': v}}]}


def _match_row(rows, book_title):
    key = normalize_key(book_title)
    exact = [r for r in rows if normalize_key(_title(r)) == key]
    if len(exact) == 1:
        return exact[0]
    prefix = [r for r in rows if normalize_key(_title(r)) and
              (key.startswith(normalize_key(_title(r))) or normalize_key(_title(r)).startswith(key))]
    return prefix[0] if len(prefix) == 1 and not exact else None


def fill_notion_row(client, data_source_id, book, isbn_addon, site_url):
    first_word = book.title.split()[0].strip(',.') if book.title.split() else book.title
    rows = client.query_by_title(data_source_id, first_word)
    row = _match_row(rows, book.title)
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
    return {'page_id': row['id'], 'filled': sorted(props), 'note': ''}
