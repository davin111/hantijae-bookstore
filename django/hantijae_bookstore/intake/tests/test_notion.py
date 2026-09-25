from datetime import date

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
