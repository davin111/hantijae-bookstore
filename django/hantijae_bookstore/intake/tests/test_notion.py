from datetime import date
from unittest import mock

import requests
from django.test import TestCase

from books.models import Book, Category
from intake import notion


def page(pid, title, **props):
    base = {
        '제목': {'type': 'title', 'title': [{'plain_text': title}]},
        '발행일': {'type': 'date', 'date': None}, 'ISBN': {'type': 'rich_text', 'rich_text': []},
        '부가기호': {'type': 'rich_text', 'rich_text': []}, '가격': {'type': 'number', 'number': None},
        '쪽수': {'type': 'number', 'number': None}, '판형': {'type': 'select', 'select': None},
        '부제': {'type': 'rich_text', 'rich_text': []}, '온라인 책창고 링크': {'type': 'url', 'url': None},
    }
    base.update(props)
    return {'id': pid, 'properties': base}


class FakeNotion:
    def __init__(self, rows, options=('130*200',)):
        self.rows, self.options, self.updates = rows, list(options), []

    def query_by_title(self, ds, text):
        return [r for r in self.rows if text in r['properties']['제목']['title'][0]['plain_text']]

    def select_options(self, ds, prop):
        return self.options

    def update_page(self, page_id, properties):
        self.updates.append((page_id, properties))


class FillNotionTest(TestCase):
    def setUp(self):
        cat = Category.objects.create(name='에세이')
        self.book = Book.objects.create(title='사그라다 파밀리아, 가족의 탄생', subtitle='부제', full_price=22000,
                                        page_count=300, size='130*200', category=cat, published_date=date(2026, 3, 2),
                                        isbn='979-11-92455-85-3', is_published=True)

    def test_fills_only_empty_properties_on_unique_prefix_match(self):
        fake = FakeNotion([page('p1', '사그라다 파밀리아', 가격={'type': 'number', 'number': 20000})])
        r = notion.fill_notion_row(fake, 'ds', self.book, '03300', 'https://hantijae-bookstore.com')
        self.assertEqual(r['page_id'], 'p1')
        props = fake.updates[0][1]
        self.assertNotIn('가격', props)                          # 이미 값 있음 → 건드리지 않음
        self.assertEqual(props['발행일'], {'date': {'start': '2026-03-02'}})
        self.assertEqual(props['판형'], {'select': {'name': '130*200'}})
        self.assertEqual(props['온라인 책창고 링크'], {'url': f'https://hantijae-bookstore.com/book={self.book.id}'})
        self.assertEqual(props['부가기호'], {'rich_text': [{'type': 'text', 'text': {'content': '03300'}}]})

    def test_no_write_when_ambiguous_or_missing(self):
        fake = FakeNotion([page('p1', '사그라다'), page('p2', '사그라다 파밀리아')])
        r = notion.fill_notion_row(fake, 'ds', self.book, '', 'https://x')
        self.assertIsNone(r['page_id'])
        self.assertEqual(fake.updates, [])
        fake = FakeNotion([])
        self.assertIsNone(notion.fill_notion_row(fake, 'ds', self.book, '', 'https://x')['page_id'])

    def test_unknown_select_option_is_skipped(self):
        fake = FakeNotion([page('p1', '사그라다 파밀리아, 가족의 탄생')], options=['152*225'])
        notion.fill_notion_row(fake, 'ds', self.book, '', 'https://x')
        self.assertNotIn('판형', fake.updates[0][1])

    def test_prefix_match_is_reported_to_admin(self):
        fake = FakeNotion([page('p1', '사그라다 파밀리아')])
        r = notion.fill_notion_row(fake, 'ds', self.book, '', 'https://x')
        self.assertEqual(r['page_id'], 'p1')
        self.assertIn('접두 일치', r['note'])
        self.assertIn('사그라다 파밀리아', r['note'])


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    def request(self, method, url, headers=None, timeout=None, **kw):
        self.calls.append((method, url, {**kw, 'timeout': timeout}))
        body = self.pages.pop(0)

        class Res:
            def raise_for_status(self):
                pass

            def json(self):
                return body
        return Res()


class NotionReadTest(TestCase):
    def test_query_pages_follows_cursor_with_date_filter(self):
        s = FakeSession([{'results': [{'id': 'a'}], 'has_more': True, 'next_cursor': 'c1'},
                         {'results': [{'id': 'b'}], 'has_more': False}])
        c = notion.NotionClient('t', session=s)
        self.assertEqual([p['id'] for p in c.query_pages('ds', '2025-09-30')], ['a', 'b'])
        first = s.calls[0][2]['json']['filter']['or']
        self.assertEqual(first[0], {'property': '발행일', 'date': {'on_or_after': '2025-09-30'}})
        self.assertEqual(s.calls[1][2]['json']['start_cursor'], 'c1')

    def test_children_follows_cursor(self):
        s = FakeSession([{'results': [{'id': 'x'}], 'has_more': True, 'next_cursor': 'n'},
                         {'results': [{'id': 'y'}], 'has_more': False}])
        c = notion.NotionClient('t', session=s)
        self.assertEqual([b['id'] for b in c.children('page')], ['x', 'y'])
        self.assertTrue(s.calls[0][1].endswith('/blocks/page/children'))
        self.assertEqual(s.calls[1][2]['params']['start_cursor'], 'n')


class _Res:
    def __init__(self, status, body, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)

    def json(self):
        return self._body


class NotionWriteTest(TestCase):
    def test_write_methods_hit_the_right_endpoints(self):
        s = FakeSession([{'id': 'db', 'data_sources': [{'id': 'ds'}]}, {'id': 'p', 'url': 'u'},
                         {'results': [{'id': 'b1'}]}, {}, {}])
        c = notion.NotionClient('t', session=s)
        c.create_database('parent', '홍보 비서 글 모음', {'이름': {'title': {}}})
        c.create_page('ds', {'이름': {}}, [{'type': 'divider', 'divider': {}}])
        self.assertEqual(c.append_children('box', [{'type': 'divider', 'divider': {}}]), [{'id': 'b1'}])
        c.update_block('b1', {'callout': {}})
        c.trash_page('p')
        (m1, u1, k1), (m2, u2, k2), (m3, u3, k3), (m4, u4, _), (m5, u5, k5) = s.calls
        self.assertEqual((m1, u1.split('/v1')[1], k1['json']['parent']), ('POST', '/databases', {'type': 'page_id', 'page_id': 'parent'}))
        self.assertIn('initial_data_source', k1['json'])
        self.assertEqual((m2, k2['json']['parent']), ('POST', {'type': 'data_source_id', 'data_source_id': 'ds'}))
        self.assertEqual((m3, u3.split('/v1')[1], k3['timeout']), ('PATCH', '/blocks/box/children', 10))
        self.assertEqual((m4, u4.split('/v1')[1]), ('PATCH', '/blocks/b1'))
        self.assertEqual((m5, u5.split('/v1')[1], k5['json']), ('PATCH', '/pages/p', {'in_trash': True}))

    def test_children_takes_a_timeout(self):
        s = FakeSession([{'results': [], 'has_more': False}])
        notion.NotionClient('t', session=s).children('box', timeout=5)
        self.assertEqual(s.calls[0][2]['timeout'], 5)

    @mock.patch('intake.notion.time.sleep')
    def test_429_waits_once_then_retries(self, sleep):
        session = mock.Mock()
        session.request.side_effect = [_Res(429, {}, {'Retry-After': '2'}), _Res(200, {'ok': 1})]
        self.assertEqual(notion.NotionClient('t', session=session).get_page('p'), {'ok': 1})
        sleep.assert_called_once_with(2.0)
