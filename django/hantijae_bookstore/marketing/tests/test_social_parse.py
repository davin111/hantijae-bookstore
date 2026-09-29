from datetime import datetime, timezone

from django.test import SimpleTestCase

from marketing.social_parse import parse_facebook, parse_instagram, parse_time, share_key
from marketing.tests.fakes import SOCIAL_ACCOUNTS, fb_item, ig_item


class ParseTest(SimpleTestCase):
    def test_facebook_share_without_own_words_keeps_original(self):
        item = fb_item('11', text='', link='https://news.example/a', previewTitle='기사 제목',
                       previewSource='news.example',
                       sharedPost={'url': 'https://www.facebook.com/author.test/posts/pfbidAbC?__cft__=x',
                                   'text': '가을 북토크 원문', 'time': '2026-09-28T00:40:16.000Z',
                                   'user': {'name': '원작성자'}})
        parsed = parse_facebook([item], SOCIAL_ACCOUNTS)
        [p] = parsed.posts
        self.assertEqual((p.platform, p.account, p.post_id, p.text), ('facebook', 'editor', '11', ''))
        self.assertEqual(p.shared, {'url': 'https://www.facebook.com/author.test/posts/pfbidAbC?__cft__=x',
                                    'text': '가을 북토크 원문', 'author': '원작성자',
                                    'posted_at': '2026-09-28T00:40:16+00:00'})
        self.assertEqual(p.link, {'url': 'https://news.example/a', 'title': '기사 제목', 'source': 'news.example'})
        self.assertEqual(p.posted_at, datetime(2026, 9, 29, 2, 35, 4, tzinfo=timezone.utc))
        self.assertIn('가을 북토크 원문', p.full_text())
        self.assertEqual(parsed.counts['editor'], {'items': 1, 'valid': 1, 'errors': 0})

    def test_accounts_mapped_by_input_url_and_unknown_counted(self):
        parsed = parse_facebook([fb_item('1', account='ceo.test', text='a'), fb_item('2', account='stranger', text='b')],
                                SOCIAL_ACCOUNTS)
        self.assertEqual([p.account for p in parsed.posts], ['ceo'])
        self.assertEqual(parsed.unknown, 1)
        self.assertEqual(parsed.counts['editor'], {'items': 0, 'valid': 0, 'errors': 0})

    def test_error_items_and_missing_fields_are_counted_not_posted(self):
        items = [{'url': 'https://www.facebook.com/editor.test', 'error': 'blocked'},
                 fb_item('3', text='x', time=None), fb_item('4', text='ok')]
        parsed = parse_facebook(items, SOCIAL_ACCOUNTS)
        self.assertEqual([p.post_id for p in parsed.posts], ['4'])
        self.assertEqual(parsed.counts['editor'], {'items': 3, 'valid': 1, 'errors': 1})

    def test_instagram_caption_and_owner(self):
        items = [ig_item('A1', caption='북토크 안내 #한티재'), {'url': 'https://www.instagram.com/editor_ig/', 'error': 'x'}]
        parsed = parse_instagram(items, SOCIAL_ACCOUNTS)
        [p] = parsed.posts
        self.assertEqual((p.platform, p.account, p.post_id, p.text, p.shared), ('instagram', 'ceo', 'A1',
                                                                                 '북토크 안내 #한티재', {}))
        self.assertEqual(parsed.counts['editor'], {'items': 1, 'valid': 0, 'errors': 1})

    def test_share_key_drops_query_and_host_variants(self):
        want = 'facebook.com/author.test/posts/pfbidAbC'
        self.assertEqual(share_key('https://m.facebook.com/author.test/posts/pfbidAbC/?__cft__=x'), want)
        self.assertEqual(share_key('https://www.facebook.com/author.test/posts/pfbidAbC'), want)

    def test_parse_time_formats(self):
        utc = datetime(2026, 9, 18, 9, 10, 34, tzinfo=timezone.utc)
        for v in ('2026-09-18T09:10:34.000Z', '2026-09-18T09:10:34+0000', 1789722634):
            self.assertEqual(parse_time(v), utc)
        self.assertIsNone(parse_time('어제'))
        self.assertIsNone(parse_time(None))

    def test_share_key_keeps_ids_in_the_query(self):
        self.assertEqual(share_key('https://www.facebook.com/photo/?fbid=123&set=a.1'), 'facebook.com/photo?fbid=123')
        self.assertNotEqual(share_key('https://www.facebook.com/photo/?fbid=1'), share_key('https://www.facebook.com/photo/?fbid=2'))
        self.assertEqual(share_key('https://m.facebook.com/permalink.php?story_fbid=9&amp;id=7'),
                         'facebook.com/permalink.php?story_fbid=9&id=7')
        self.assertEqual(share_key('https://www.facebook.com/watch/?v=55&ref=x'), 'facebook.com/watch?v=55')
