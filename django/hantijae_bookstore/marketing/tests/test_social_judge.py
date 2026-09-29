from datetime import datetime, timedelta, timezone

from django.test import TestCase

from marketing.social_judge import assign_group
from marketing.tests.fakes import make_post

T0 = datetime(2026, 9, 18, 9, 10, tzinfo=timezone.utc)
BODY = '『농부, 짠한 형』이 나왔습니다. 알라딘 북펀드로 먼저 만나 보세요. 많은 관심 부탁드립니다.'


class GroupTest(TestCase):
    def test_same_shared_original_is_one_group(self):
        a = make_post('1', shared={'url': 'https://www.facebook.com/hantijae/posts/pfbidX?__cft__=1', 'text': '원문'})
        b = make_post('2', account='ceo', shared={'url': 'https://m.facebook.com/hantijae/posts/pfbidX/', 'text': '원문'})
        self.assertEqual(assign_group(a), 'share:facebook.com/hantijae/posts/pfbidX')
        self.assertEqual(assign_group(b), assign_group(a))

    def test_instagram_copy_joins_facebook_group_within_three_days(self):
        make_post('fb1', account='ceo', text=BODY, posted_at=T0)
        ig = make_post('ig1', platform='instagram', account='ceo', text=BODY + '\n#한티재의책', group_key='',
                       posted_at=T0 + timedelta(minutes=5))
        self.assertEqual(assign_group(ig), 'post:facebook:fb1')

    def test_far_apart_or_short_posts_stay_alone(self):
        make_post('fb1', account='ceo', text=BODY, posted_at=T0)
        make_post('fb2', text='좋은 아침', posted_at=T0)
        late = make_post('ig1', platform='instagram', account='ceo', text=BODY, group_key='', posted_at=T0 + timedelta(days=4))
        short = make_post('ig2', platform='instagram', text='좋은 아침', group_key='', posted_at=T0)
        self.assertEqual(assign_group(late), 'post:instagram:ig1')
        self.assertEqual(assign_group(short), 'post:instagram:ig2')
