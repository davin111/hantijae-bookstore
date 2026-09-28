from datetime import datetime, timedelta, timezone

from django.test import TestCase

from context.models import ContextEntry
from context.retention import purge
from context.stats import summary_lines

NOW = datetime(2026, 9, 29, 3, 0, tzinfo=timezone.utc)


def entry(key, at, **kw):
    return ContextEntry.objects.create(key=key, at=at, **kw)


class RetentionTest(TestCase):
    def test_purge_deletes_only_older_than_retention(self):
        entry('old', NOW - timedelta(days=90, seconds=1))
        entry('edge', NOW - timedelta(days=90))
        entry('new', NOW - timedelta(days=1))
        self.assertEqual(purge(NOW), 1)
        self.assertEqual(set(ContextEntry.objects.values_list('key', flat=True)), {'edge', 'new'})

    def test_purge_days_override(self):
        entry('a', NOW - timedelta(days=2))
        self.assertEqual(purge(NOW, days=1), 1)


class SummaryTest(TestCase):
    def test_empty(self):
        self.assertEqual(summary_lines(NOW), ['보관 90일 · 기록 0건'])

    def test_counts_redactions_and_unknown_people(self):
        entry('tgx:1:1', NOW - timedelta(days=30), origin='export', author_name='대표님', role='운영진A')
        entry('tg:1:2', NOW - timedelta(days=1), author_id=77, author_name='검수자A', redactions={'phone': 2})
        entry('tg:1:3', NOW - timedelta(hours=1), author_id=77, author_name='검수자A', redactions={'phone': 1, 'account': 1})
        text = '\n'.join(summary_lines(NOW))
        self.assertIn('기록 3건', text)
        self.assertIn('가장 오래된 기록 2026-08-30 12:00', text)
        self.assertIn('실시간 시작 2026-09-28 12:00', text)
        self.assertIn('최근 7일 가림: 전화 3 · 계좌 1', text)
        self.assertIn('역할 없는 사람: 검수자A(77) 2건', text)
        self.assertNotIn('대표님', text)

    def test_forgotten_rows_are_not_counted(self):
        entry('tg:1:9', NOW - timedelta(hours=1), author_id=78, author_name='검수자B', forgotten=True)
        self.assertEqual(summary_lines(NOW), ['보관 90일 · 기록 0건'])
