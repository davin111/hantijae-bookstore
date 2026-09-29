from datetime import datetime, timezone

from django.test import TestCase

from context import notion as N
from context.models import ContextEntry

NOW = datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc)
RECENT, OLD = '2026-09-25T01:00:00.000Z', '2025-05-02T06:51:00.000Z'


def rt(text):
    return [{'plain_text': text}]


def block(bid, kind, text='', edited=RECENT, children=False, **extra):
    v = {'rich_text': rt(text)} if kind != 'table_row' else {'cells': [rt(c) for c in text.split('|')]}
    v.update(extra)
    return {'id': bid, 'type': kind, kind: v, 'has_children': children, 'last_edited_time': edited}


def page(pid='p1', edited=RECENT, **props):
    base = {'제목': {'type': 'title', 'title': rt('무궁화호를 위하여')},
            '발행일': {'type': 'date', 'date': {'start': '2026-10-20'}},
            '상태': {'type': 'select', 'select': {'name': '출간 예정'}},
            '선정 / 추천 / 수상': {'type': 'rich_text', 'rich_text': rt('AI 오디오북 제작 지원 선정')},
            '전자책': {'type': 'checkbox', 'checkbox': False},
            '': {'type': 'number', 'number': 3},
            '저자': {'type': 'relation', 'relation': [{'id': 'x'}]},
            '마감 일정': {'type': 'date', 'date': None}}
    base.update(props)
    return {'id': pid, 'last_edited_time': edited, 'properties': base}


class FakeClient:
    def __init__(self, pages, tree):
        self.pages, self.tree, self.calls = pages, tree, 0

    def query_pages(self, ds, published_after):
        self.published_after = published_after
        return self.pages

    def children(self, block_id):
        self.calls += 1
        return self.tree.get(block_id, [])


def no_sleep(_):
    pass


TREE = {
    'p1': [block('b0', 'paragraph', '페이지 머리 메모'),
           block('t1', 'toggle', '2026. 9. 20. 통화', children=True),
           block('h1', 'heading_2', '홍보 계획'),
           block('b1', 'bulleted_list_item', '10월 북토크 추진', children=True),
           block('t2', 'toggle', '2025년 5월 2일(금) 통화', edited=OLD, children=True),
           block('t3', 'toggle', '빈 토글', children=True),
           block('img', 'image')],
    't1': [block('c1', 'paragraph', '저자가 10월 17일 대구에서 강연. 연락 010-1234-5678'),
           block('c2', 'to_do', '포스터 받기', checked=True),
           block('tbl', 'table', children=True)],
    'tbl': [block('r1', 'table_row', '날짜|장소'), block('r2', 'table_row', '10/17|대구')],
    'b1': [block('c3', 'paragraph', '장소는 미정')],
    't2': [block('c4', 'paragraph', '옛 통화', edited=OLD)],
}


class NotionSectionTest(TestCase):
    def test_props_section_skips_unnamed_relation_and_empty(self):
        s = N.props_section(page())
        self.assertEqual(s.key, 'notion:p1:props')
        self.assertEqual(s.text.split('\n'), ['제목: 무궁화호를 위하여', '발행일: 2026-10-20', '상태: 출간 예정',
                                              '선정 / 추천 / 수상: AI 오디오북 제작 지원 선정'])

    def test_sync_records_sections_with_redaction(self):
        client = FakeClient([page()], TREE)
        self.assertEqual(N.sync(client, 'ds', NOW, sleep=no_sleep), 4)
        self.assertEqual(client.published_after, '2025-09-29')
        rows = {e.key: e for e in ContextEntry.objects.all()}
        self.assertEqual(set(rows), {'notion:p1:props', 'notion:p1:top', 'notion:t1', 'notion:h1'})
        t1 = rows['notion:t1']
        self.assertEqual((t1.source, t1.origin, t1.heading), ('notion', 'live', '『무궁화호를 위하여』 · 2026. 9. 20. 통화'))
        self.assertEqual(t1.text, '  저자가 10월 17일 대구에서 강연. 연락 [전화]\n  [x] 포스터 받기\n    날짜 | 장소\n    10/17 | 대구')
        self.assertEqual(t1.redactions, {'phone': 1})
        self.assertEqual(rows['notion:h1'].text, '10월 북토크 추진\n  장소는 미정\n[image]')
        self.assertEqual(rows['notion:p1:top'].heading, '『무궁화호를 위하여』 · 머리')
        self.assertEqual(t1.at, datetime(2026, 9, 25, 1, 0, tzinfo=timezone.utc))

    def test_resync_only_counts_changes_and_keeps_forgotten(self):
        N.sync(FakeClient([page()], TREE), 'ds', NOW, sleep=no_sleep)
        self.assertEqual(N.sync(FakeClient([page()], TREE), 'ds', NOW, sleep=no_sleep), 0)
        changed = dict(TREE, b1=[block('c3', 'paragraph', '장소는 대구 ○○서점')])
        self.assertEqual(N.sync(FakeClient([page()], changed), 'ds', NOW, sleep=no_sleep), 1)
        h1 = ContextEntry.objects.get(key='notion:h1')
        self.assertEqual((h1.edited_at, '○○서점' in h1.text), (NOW, True))
        ContextEntry.objects.filter(key='notion:h1').update(forgotten=True, text='')
        again = dict(TREE, b1=[block('c3', 'paragraph', '또 바뀜')])
        N.sync(FakeClient([page()], again), 'ds', NOW, sleep=no_sleep)
        self.assertEqual(ContextEntry.objects.get(key='notion:h1').text, '')

    def test_old_sections_are_not_recorded(self):
        N.sync(FakeClient([page(edited=OLD)], {'p1': [TREE['p1'][4]], 't2': TREE['t2']}), 'ds', NOW, sleep=no_sleep)
        self.assertFalse(ContextEntry.objects.exists())

    def test_toggleable_heading_is_its_own_section(self):
        tree = {'p1': [block('h9', 'heading_3', '저자 통화', children=True, is_toggleable=True)],
                'h9': [block('c9', 'paragraph', '11월 방송 출연')]}
        N.sync(FakeClient([page(**{'선정 / 추천 / 수상': {'type': 'rich_text', 'rich_text': []}})], tree), 'ds', NOW,
               sleep=no_sleep)
        self.assertEqual(ContextEntry.objects.get(key='notion:h9').text, '  11월 방송 출연')

    def test_section_keys_are_unique_when_toggles_split_loose_blocks(self):
        top = [(block('a', 'paragraph', '앞'), []), (block('t', 'toggle', '통화'), [(1, block('x', 'paragraph', '안'))]),
               (block('b', 'paragraph', '뒤'), [])]
        secs = N.sections(page(), top)
        self.assertEqual([s.key for s in secs], ['notion:p1:top', 'notion:t'])
        self.assertEqual(secs[0].text, '앞\n뒤')
