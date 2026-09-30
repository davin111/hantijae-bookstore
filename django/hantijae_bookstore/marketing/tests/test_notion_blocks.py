from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from marketing import notion_blocks as nb
from marketing.messages import OPEN, POSTED, SKIPPED
from marketing.models import Draft


def blk(kind, text, bid='x'):
    return {'id': bid, 'type': kind, kind: {'rich_text': [{'plain_text': text}]}}


class NotionBlocksTest(SimpleTestCase):
    def test_rich_splits_at_2000_utf16_units(self):
        self.assertEqual([len(x['text']['content']) for x in nb.rich('가' * 4500)], [2000, 2000, 500])
        emoji = nb.rich('😀' * 1001)  # 이모지는 2단위 → 1000개씩
        self.assertEqual([len(x['text']['content']) for x in emoji], [1000, 1])
        self.assertEqual(nb.rich(''), [{'type': 'text', 'text': {'content': ''}}])
        self.assertEqual(nb.rich('제목', bold=True)[0]['annotations'], {'bold': True})

    def test_page_blocks_have_at_most_two_levels(self):
        blocks = nb.page_blocks('허브 글', [('1. 항목', '이유'), ('2. 항목', '')], caution='조심')
        kinds = [b['type'] for b in blocks]
        self.assertEqual(kinds, ['callout', 'callout', 'paragraph', 'divider', 'heading_3', 'heading_3'])
        first = blocks[4]['heading_3']
        self.assertTrue(first['is_toggleable'])
        self.assertEqual([c['type'] for c in first['children']], ['callout', 'callout'])
        self.assertNotIn('children', first['children'][1]['callout'])  # 📝 상자 속 글은 따로 덧붙인다
        self.assertEqual(len(blocks[5]['heading_3']['children']), 1)  # 메모가 없으면 📝 상자만

    def test_box_content_is_one_block_per_part(self):
        self.assertEqual([b['paragraph']['rich_text'][0]['text']['content'] for b in nb.box_content('제목', '줄1\n\n줄2')],
                         ['제목', '줄1\n\n줄2'])
        self.assertEqual(len(nb.box_content('', '글')), 1)

    def test_read_box_joins_split_blocks_and_lists(self):
        blocks = [blk('paragraph', '제목', 't1'), blk('paragraph', '첫 줄'), blk('paragraph', ''),
                  blk('bulleted_list_item', '가'), blk('numbered_list_item', '하나'), blk('numbered_list_item', '둘'),
                  blk('paragraph', '끝'), blk('image', '')]
        self.assertEqual(nb.read_box(blocks, 't1'), ('제목', '첫 줄\n\n· 가\n1. 하나\n2. 둘\n끝'))
        self.assertEqual(nb.read_box([blk('paragraph', '한 블록\n\n안의 글')]), ('', '한 블록\n\n안의 글'))

    def test_normalize(self):
        self.assertEqual(nb.normalize('가 \r\n나 다  \n\n'), '가\n나 다')

    def test_headings_and_progress(self):
        self.assertEqual(nb.heading_text('1. 항목', POSTED), '✅ 1. 항목')
        self.assertEqual(nb.heading_text('블로그 글', SKIPPED), '넘김 · 블로그 글')
        self.assertEqual(nb.progress([POSTED, SKIPPED, OPEN, OPEN]), '✅ 1 · 넘김 1 · 남음 2')
        self.assertEqual(nb.progress([]), '—')
        props = nb.page_properties('9월 28일 주 홍보 제안', '주간 브리핑', date(2026, 9, 30), [OPEN])
        self.assertEqual(props['종류'], {'select': {'name': '주간 브리핑'}})
        self.assertEqual(props['날짜'], {'date': {'start': '2026-09-30'}})

    def test_memos(self):
        p = SimpleNamespace(reason='이유', extra={'link': 'https://a', 'link_label': '기사 원문'})
        d = SimpleNamespace(label='보낼 글', extra={'places': ['농민회', '생협'], 'to': '농민회'}, channel=Draft.LETTER)
        self.assertEqual(nb.item_memo(p, d), '이유\n기사 원문: https://a\n어떤 글: 보낼 글\n알리면 좋을 곳: 농민회, 생협\n보낼 곳: 농민회')
        links = SimpleNamespace(label='서점 링크 공지', extra={}, channel=Draft.LINKS)
        self.assertEqual(nb.kit_memo(links), '카톡이나 단체방에 그대로 붙이시면 돼요.')
        self.assertEqual(nb.kit_memo(SimpleNamespace(label='블로그 글', extra={}, channel=Draft.BLOG)), '')

    def test_version_blocks(self):
        label, box = nb.version_blocks(3, '해시태그를 줄여 주세요' * 10)
        text = label['paragraph']['rich_text'][0]['text']['content']
        self.assertTrue(text.startswith('고친 글 3 · 요청: "해시태그를'))
        self.assertLessEqual(len(text), 80)
        self.assertEqual(box['callout']['rich_text'][0]['text']['content'], nb.BOX_LABEL)
