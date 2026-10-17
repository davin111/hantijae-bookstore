from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import TestCase

from context import notion as N
from context.models import ContextEntry
from context.tests.test_notion import block, rt

NOW = datetime(2026, 10, 17, 8, tzinfo=timezone.utc)
RECENT = '2026-10-10T03:00:00Z'
OLD = '2025-06-01T03:00:00Z'


def prop(kind, value, **extra):
    return {'type': kind, kind: value, **extra}


def row(pid='w1', kind='work', **overrides):
    props = {'관련 책': prop('relation', [{'id': 'book'}], id='books', has_more=False)}
    if kind == 'work':
        props.update({'내용 요약': prop('title', []), '날짜': prop('date', {'start': '2026-10-07'}),
                      '후속 조치': prop('rich_text', rt('내년 3~4월 원고 전달. 연락 010-1234-5678')),
                      '종류': prop('select', {'name': '통화'}), '상대': prop('rich_text', rt('수집하지 않을 연락처'))})
    else:
        props.update({'작업 이름': prop('title', rt('가목차 입수')), '상태': prop('status', {'name': '진행 중'}),
                      '마감일': prop('date', {'start': '2026-10-19'}), '반복 업무': prop('checkbox', False),
                      '구분': prop('select', None), '메모': prop('rich_text', [])})
    props.update(overrides)
    return {'id': pid, 'created_time': OLD, 'last_edited_time': RECENT, 'properties': props}


class Client:
    def __init__(self):
        self.books = [{'id': 'book', 'properties': {'제목': prop('title', rt('농촌사회학 개론서'))}}]
        self.rows = {'work': [row()], 'tasks': [row('t1', 'task')]}
        self.tree = {}
        self.more = []
        self.relations_read = []
        self.gone = {}

    def data_source(self, ds):
        if ds == 'catalog':
            return {'properties': {name: prop('relation', {'data_source_id': target})
                                   for name, target in [('업무 기록', 'work'), ('할 일', 'tasks')]}}
        fields = {'내용 요약': 'title', '날짜': 'date', '종류': 'select', '후속 조치': 'rich_text'} if ds == 'work' else {
            '작업 이름': 'title', '상태': 'status', '마감일': 'date', '구분': 'select', '메모': 'rich_text', '반복 업무': 'checkbox'}
        return {'properties': {'관련 책': prop('relation', {'data_source_id': 'catalog'}),
                               **{k: {'type': v} for k, v in fields.items()}}}

    def query_all_pages(self, ds):
        return self.books if ds == 'catalog' else self.rows[ds]

    def query_pages(self, ds, after):
        return []

    def children(self, pid):
        return self.tree.get(pid, [])

    def relation_ids(self, pid, p):
        self.relations_read.append(pid)
        return self.more if p.get('has_more') else [r['id'] for r in p['relation']]

    def get_page(self, pid):
        return self.gone[pid]


class WorkSyncTest(TestCase):
    def setUp(self):
        self.client = Client()

    def sync(self, now=NOW):
        return N.sync(self.client, 'catalog', now, sleep=lambda _: None, related=True)

    def test_real_shapes_blank_work_title_and_old_book_are_collected_once(self):
        self.assertEqual(self.sync(), 2)
        rows = list(ContextEntry.objects.order_by('key'))
        self.assertTrue(all(e.key.startswith('notion-work:') for e in rows))
        work = ContextEntry.objects.get(key='notion-work:work:w1')
        self.assertIn('농촌사회학 개론서', work.heading)
        self.assertIn('2026-10-07', work.text)
        self.assertIn('내년 3~4월 원고', work.text)
        self.assertNotIn('010-1234-5678', work.text)
        self.assertNotIn('수집하지 않을 연락처', work.text)
        self.assertIn('2026-10-19', ContextEntry.objects.get(key='notion-work:tasks:t1').text)
        self.assertEqual(self.sync(), 0)

    def test_old_completed_repeated_unlinked_and_empty_rows_are_skipped(self):
        self.client.rows['work'] += [row('old', 날짜=prop('date', {'start': '2024-10-10'})),
                                    row('empty', **{'후속 조치': prop('rich_text', [])}),
                                    row('unlinked', **{'관련 책': prop('relation', [])})]
        self.client.rows['tasks'] += [row('done', 'task', 상태=prop('status', {'name': '완료'})),
                                     row('repeat', 'task', **{'반복 업무': prop('checkbox', True)}),
                                     row('undated', 'task', 마감일=prop('date', None)),
                                     row('past', 'task', 마감일=prop('date', {'start': '2024-10-19'}))]
        self.assertEqual(self.sync(), 2)

    def test_body_and_long_relation_are_read_without_descending_other_tables(self):
        self.client.rows['work'][0]['properties']['관련 책']['has_more'] = True
        self.client.more = ['other'] * 25 + ['book', 'book']
        self.client.gone['other'] = {'id': 'other', 'in_trash': True}
        self.client.tree['w1'] = [block('b', 'paragraph', '원고 검토 중'),
                                  block('child', 'child_page', children=True)]
        self.client.tree['child'] = [block('secret', 'paragraph', '범위 밖')]
        self.sync()
        w = ContextEntry.objects.get(key='notion-work:work:w1')
        self.assertIn('원고 검토 중', w.text)
        self.assertNotIn('범위 밖', w.text)
        self.assertIn('w1', self.client.relations_read)

    def test_completion_unlink_and_archiving_clear_context_and_reopen_restores(self):
        self.sync()
        self.client.rows['tasks'][0]['properties']['상태']['status']['name'] = '완료'
        self.client.rows['work'][0]['properties']['관련 책']['relation'] = []
        self.assertEqual(self.sync(), 2)
        self.assertFalse(ContextEntry.objects.exclude(text='').exists())
        self.client.rows['work'] = [row()]
        self.assertEqual(self.sync(), 1)
        self.client.rows['work'] = []
        self.client.gone['w1'] = {'id': 'w1', 'in_trash': True}
        self.assertEqual(self.sync(), 1)
        self.assertEqual(ContextEntry.objects.get(key='notion-work:work:w1').text, '')

    def test_forgotten_and_unchanged_rows_follow_observation_time_without_new_version(self):
        self.sync()
        w = ContextEntry.objects.get(key='notion-work:work:w1')
        ContextEntry.objects.filter(pk=w.pk).update(forgotten=True, text='')
        t = ContextEntry.objects.get(key='notion-work:tasks:t1')
        version = t.changed_at
        self.assertEqual(self.sync(NOW + timedelta(days=1)), 0)
        w.refresh_from_db(); t.refresh_from_db()
        self.assertEqual(w.text, '')
        self.assertEqual(w.at, NOW + timedelta(days=1))
        self.assertEqual(t.changed_at, version)

    def test_partial_read_or_permission_failure_preserves_previous_snapshot(self):
        self.sync()
        before = list(ContextEntry.objects.order_by('key').values('key', 'text', 'at'))
        self.client.rows['tasks'] = []
        self.client.get_page = mock.Mock(side_effect=RuntimeError('403 denied'))
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(list(ContextEntry.objects.order_by('key').values('key', 'text', 'at')), before)

    def test_replaced_target_relation_is_not_silently_accepted(self):
        self.sync()
        original = self.client.data_source
        self.client.data_source = lambda ds: ({'properties': {'관련 책': prop('relation', {'data_source_id': 'private'})}}
                                               if ds == 'work' else original(ds))
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(ContextEntry.objects.exclude(text='').count(), 2)

    def test_table_query_failure_does_not_hide_existing_book_sync_error(self):
        self.client.query_all_pages = mock.Mock(side_effect=RuntimeError('429'))
        with self.assertRaisesRegex(RuntimeError, '429'):
            self.sync()

    def test_missing_catalog_book_does_not_mean_unlinked(self):
        self.sync()
        self.client.books = []
        self.client.get_page = mock.Mock(side_effect=RuntimeError('403 denied'))
        with self.assertRaisesRegex(RuntimeError, '403'):
            self.sync()
        self.assertEqual(ContextEntry.objects.exclude(text='').count(), 2)
        self.client.get_page = mock.Mock(return_value={'id': 'book', 'in_trash': True})
        self.assertEqual(self.sync(), 2)

    def test_missing_status_schema_preserves_tasks(self):
        self.sync()
        original = self.client.data_source
        def renamed(ds):
            schema = original(ds)
            if ds == 'tasks':
                del schema['properties']['상태']
            return schema
        self.client.data_source = renamed
        del self.client.rows['tasks'][0]['properties']['상태']
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(ContextEntry.objects.exclude(text='').count(), 2)

    def test_missing_row_status_after_schema_read_preserves_tasks(self):
        self.sync()
        del self.client.rows['tasks'][0]['properties']['상태']
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(ContextEntry.objects.exclude(text='').count(), 2)

    def test_forgotten_completed_task_cannot_reappear_after_retention(self):
        from context.retention import purge
        self.sync()
        ContextEntry.objects.filter(key='notion-work:tasks:t1').update(forgotten=True, text='', heading='')
        self.client.rows['tasks'][0]['properties']['상태']['status']['name'] = '완료'
        later = NOW + timedelta(days=91)
        self.sync(later)
        purge(later)
        task = self.client.rows['tasks'][0]['properties']
        task['상태']['status']['name'] = '진행 중'
        task['마감일']['date']['start'] = later.date().isoformat()
        self.sync(later)
        stored = ContextEntry.objects.get(key='notion-work:tasks:t1')
        self.assertTrue(stored.forgotten)
        self.assertEqual(stored.text, '')
