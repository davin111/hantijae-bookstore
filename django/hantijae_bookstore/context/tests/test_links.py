import json
from datetime import datetime

from django.test import TestCase

from context import links as L
from context.models import FORGET_FIELDS, ContextEntry
from context.record import apply_edit
from context.tests.test_record import tg_msg
from marketing.timeutil import KST

NOW = datetime(2026, 10, 1, 5, 0, tzinfo=KST)
VID = 'SmBkSfcS8nM'
PLAYER = {
    'videoDetails': {'videoId': VID, 'title': '한때 여자 김광석이라 불리던 가수｜한국기행', 'author': 'EBSDocumentary (EBS 다큐)',
                     'viewCount': '658084',
                     'shortDescription': '※이 영상은 2026년 9월 11일에 방송된 <한국기행>의 일부입니다.\n\n문의 010-1234-5678'},
    'microformat': {'playerMicroformatRenderer': {'publishDate': '2026-09-29T00:30:10-07:00'}},
}
PAGE = f'<html><script>var ytInitialPlayerResponse = {json.dumps(PLAYER, ensure_ascii=False)};var meta = {{}};</script></html>'


def entry(n, text, **kw):
    return ContextEntry.objects.create(key=f'tg:-259:{n}', chat_id=-259, message_id=n, at=NOW, role='운영진C', text=text,
                                       **kw)


class VideoIdsTest(TestCase):
    def test_common_link_forms(self):
        text = ('https://youtu.be/SmBkSfcS8nM?si=i7_XLYFu-EKAvrlZ 그리고 https://www.youtube.com/watch?v=PbAYbNCJ_YU '
                'https://m.youtube.com/watch?feature=share&v=abcdefghij1 youtube.com/shorts/abcdefghij2 '
                'https://www.youtube.com/live/abcdefghij3?x=1 다시 https://youtu.be/SmBkSfcS8nM')
        self.assertEqual(L.video_ids(text), ['SmBkSfcS8nM', 'PbAYbNCJ_YU', 'abcdefghij1', 'abcdefghij2', 'abcdefghij3'])

    def test_other_links_and_broken_ids(self):
        self.assertEqual(L.video_ids('https://blog.naver.com/x https://youtu.be/short https://youtu.be/abcdefghij12345'), [])


class YoutubeInfoTest(TestCase):
    def test_reads_player_response(self):
        urls = []

        def get(url):
            urls.append(url)
            return PAGE
        info = L.youtube_info(VID, get)
        self.assertEqual(urls, [f'https://www.youtube.com/watch?v={VID}'])
        self.assertEqual((info['title'], info['channel'], info['published'], info['views']),
                         ('한때 여자 김광석이라 불리던 가수｜한국기행', 'EBSDocumentary (EBS 다큐)', '2026-09-29', 658084))
        self.assertIn('9월 11일에 방송된', info['description'])

    def test_falls_back_to_oembed(self):
        def get(url):
            if 'oembed' in url:
                self.assertIn(f'watch?v={VID}', url)
                return json.dumps({'title': '제목만', 'author_name': '채널'})
            return '<html>consent</html>'
        self.assertEqual(L.youtube_info(VID, get),
                         {'title': '제목만', 'channel': '채널', 'published': '', 'views': None, 'description': ''})


class ReadLinksTest(TestCase):
    def test_saves_redacted_summary_and_marks_read(self):
        e = entry(1, f'박강수 방송. https://youtu.be/{VID}?si=abc')
        self.assertEqual(L.read_links([e], NOW, lambda url: PAGE), 1)
        e.refresh_from_db()
        self.assertEqual(e.link_read_at, NOW)
        first, second = e.link_text.split('\n')
        self.assertEqual(first, '[유튜브] 「한때 여자 김광석이라 불리던 가수｜한국기행」 · EBSDocumentary (EBS 다큐) · 2026-09-29 공개 · '
                                '조회 수 658,084회(10/1 05:00 기준)')
        self.assertTrue(second.startswith('설명: ※이 영상은 2026년 9월 11일에 방송된 <한국기행>의 일부입니다. 문의'))
        self.assertIn('[전화]', second)
        self.assertNotIn('5678', e.link_text)

    def test_skips_entries_without_youtube_already_read_or_forgotten(self):
        plain = entry(1, '링크 없음 https://blog.naver.com/x')
        done = entry(2, f'https://youtu.be/{VID}', link_read_at=NOW, link_text='이전')
        gone = entry(3, '', forgotten=True)

        def get(url):
            raise AssertionError('읽으면 안 됨')
        self.assertEqual(L.read_links([plain, done, gone], NOW, get), 0)
        plain.refresh_from_db()
        self.assertIsNone(plain.link_read_at)

    def test_failure_marks_read_without_text(self):
        e = entry(1, f'https://youtu.be/{VID}')

        def get(url):
            raise ConnectionError('down')
        self.assertEqual(L.read_links([e], NOW, get), 0)
        e.refresh_from_db()
        self.assertEqual((e.link_text, e.link_read_at), ('', NOW))  # 한 번만 해 보고 넘어간다(계기 잡기를 막지 않음)


class LinkFieldsLifecycleTest(TestCase):
    def test_forget_clears_link_text(self):
        self.assertEqual(FORGET_FIELDS['link_text'], '')

    def test_edit_that_changes_text_resets_link_reading(self):
        e = ContextEntry.objects.create(key='tg:-259:10', chat_id=-259, message_id=10, at=NOW, text='안녕하세요',
                                        link_text='[유튜브] 옛 영상', link_read_at=NOW)
        apply_edit(tg_msg(10, f'바꾼 링크 https://youtu.be/{VID}', chat={'id': -259, 'type': 'group'}, edit_date=1790000000))
        e.refresh_from_db()
        self.assertEqual((e.link_text, e.link_read_at), ('', None))
