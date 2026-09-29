from datetime import date, datetime, timedelta, timezone

from django.test import TestCase

from marketing import social_judge as J
from marketing.models import Signal, SocialPost
from marketing.social_judge import assign_group
from marketing.tests.fakes import FakeLLM, make_book, make_post
from marketing.timeutil import KST

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

    def test_share_of_a_colleagues_post_joins_it_either_order(self):
        orig = make_post('o1', account='ceo', text='원글', posted_at=T0)
        orig.url = 'https://www.facebook.com/ceo.test/posts/pfbidAAA'
        orig.save()
        share = make_post('s1', shared={'url': 'https://www.facebook.com/ceo.test/posts/pfbidAAA?__cft__=z', 'text': '원글'},
                          group_key='')
        self.assertEqual(assign_group(share), 'post:facebook:o1')
        share2 = make_post('s2', shared={'url': 'https://www.facebook.com/ceo.test/posts/pfbidBBB', 'text': '원글2'},
                           group_key='share:facebook.com/ceo.test/posts/pfbidBBB')
        later = make_post('o2', account='ceo', text='원글2', group_key='')
        later.url = 'https://www.facebook.com/ceo.test/posts/pfbidBBB'
        later.save()
        self.assertEqual(assign_group(later), share2.group_key)

    def test_far_apart_or_short_posts_stay_alone(self):
        make_post('fb1', account='ceo', text=BODY, posted_at=T0)
        make_post('fb2', text='좋은 아침', posted_at=T0)
        late = make_post('ig1', platform='instagram', account='ceo', text=BODY, group_key='', posted_at=T0 + timedelta(days=4))
        short = make_post('ig2', platform='instagram', text='좋은 아침', group_key='', posted_at=T0)
        self.assertEqual(assign_group(late), 'post:instagram:ig1')
        self.assertEqual(assign_group(short), 'post:instagram:ig2')

NOW = datetime(2026, 9, 30, 6, 25, tzinfo=KST)
LABELS = {'editor': '편집장', 'ceo': '대표'}


def verdict(i=0, **kw):
    v = {'id': i, 'relevant': True, 'private': False, 'sensitive': False, 'category': 'other', 'books': [],
         'event': None, 'summary': '요약'}
    v.update(kw)
    return v


class JudgeTest(TestCase):
    def setUp(self):
        self.rainbow = make_book(title='무지개를 변호하다', published=date(2026, 6, 1), isbn='979-11-00000-14-1', author='박한희')
        self.farmer = make_book(title='농부, 짠한 형', published=date(2026, 9, 10), isbn='979-11-00000-15-1', author=None)

    def post(self, pid, **kw):
        kw.setdefault('posted_at', datetime(2026, 9, 29, 11, 0, tzinfo=KST))
        return make_post(pid, **kw)

    def test_share_without_own_words_is_judged_from_original(self):
        p = self.post('1', shared={'url': 'https://www.facebook.com/a/posts/X', 'author': '원작성자',
                                   'posted_at': '2026-09-28T00:40:16+00:00',
                                   'text': '『무지개를 변호하다』 북토크가 10월 12일 대구에서 열립니다'})
        llm = FakeLLM({'items': [verdict(category='event', books=['무지개를 변호하다'],
                                         event={'date': '2026-10-12', 'name': '북토크', 'place': '대구'},
                                         summary='북토크 안내')]})
        [s] = J.judge_pending(llm, NOW, LABELS)
        self.assertEqual((s.kind, s.book, s.happens_on, s.relevant), (Signal.SOCIAL, self.rainbow, date(2026, 10, 12), True))
        self.assertEqual(s.detail['event'], {'on': '2026-10-12', 'name': '북토크', 'place': '대구'})
        self.assertEqual((s.detail['who'], s.detail['platforms'], s.detail['posted_on']), (['편집장'], ['facebook'], '2026-09-29'))
        p.refresh_from_db()
        self.assertEqual(p.signal, s)
        user = llm.calls[0][1]
        self.assertIn('공유한 원문(원작성자 원작성자, 2026-09-28)', user)
        self.assertIn('무지개를 변호하다 |', user)

    def test_invented_title_and_unmentioned_date_are_dropped(self):
        self.post('1', text='가을 북토크 소식을 곧 전하겠습니다')
        llm = FakeLLM({'items': [verdict(category='event', books=['없는 책'],
                                         event={'date': '2026-10-12', 'name': '북토크', 'place': ''})]})
        [s] = J.judge_pending(llm, NOW, LABELS)
        self.assertEqual((s.detail['books'], s.detail['titles'], s.book), ([], [], None))
        self.assertEqual(s.detail['event'], {'on': '', 'name': '북토크', 'place': ''})
        self.assertEqual(s.happens_on, date(2026, 9, 29))

    def test_unregistered_title_kept_then_linked_later(self):
        self.post('1', text='한티재 신간 『바람의 책』이 곧 나옵니다')
        [s] = J.judge_pending(FakeLLM({'items': [verdict(category='new_book', books=['바람의 책'])]}), NOW, LABELS)
        self.assertEqual((s.book, s.detail['titles']), (None, ['바람의 책']))
        self.assertEqual(J.link_later(NOW), 0)
        wind = make_book(title='바람의 책', isbn='979-11-00000-16-1', author=None)
        self.assertEqual(J.link_later(NOW), 1)
        s.refresh_from_db()
        self.assertEqual((s.book, s.detail['books'], s.detail['titles']), (wind, [wind.id], []))

    def test_irrelevant_or_private_posts_make_no_signal(self):
        self.post('1', text='오늘 저녁은 오이 장아찌')
        self.post('2', text='가족 이야기와 『농부, 짠한 형』')
        llm = FakeLLM({'items': [verdict(0, relevant=False), verdict(1, private=True, books=['농부, 짠한 형'])]})
        self.assertEqual(J.judge_pending(llm, NOW, LABELS), [])
        self.assertEqual(Signal.objects.count(), 0)
        self.assertEqual(SocialPost.objects.filter(judged_at__isnull=False).count(), 2)

    def test_copy_in_same_group_follows_without_llm(self):
        fb = self.post('fb1', account='ceo', text='『농부, 짠한 형』 펀딩')
        [s] = J.judge_pending(FakeLLM({'items': [verdict(category='funding', books=['농부, 짠한 형'])]}), NOW, LABELS)
        ig = self.post('ig1', platform='instagram', account='ceo', text='『농부, 짠한 형』 펀딩', group_key=fb.group_key)
        self.assertEqual(J.judge_pending(FakeLLM([]), NOW, LABELS), [s])  # FakeLLM([])는 부르면 터진다
        ig.refresh_from_db()
        s.refresh_from_db()
        self.assertEqual((ig.signal, ig.verdict), (s, {'follows': fb.id}))
        self.assertEqual((s.detail['platforms'], s.detail['who']), (['facebook', 'instagram'], ['대표']))

    def test_same_event_from_other_person_joins_signal(self):
        self.post('1', account='ceo', text='10월 12일 『무지개를 변호하다』 북토크에 오세요')
        self.post('2', text='다음 달 10월 12일 북토크, 『무지개를 변호하다』 함께 읽어요')
        ev = {'date': '2026-10-12', 'name': '북토크', 'place': ''}
        llm = FakeLLM({'items': [verdict(0, category='event', books=['무지개를 변호하다'], event=ev),
                                 verdict(1, category='event', books=['무지개를 변호하다'], event=ev)]})
        signals = J.judge_pending(llm, NOW, LABELS)
        self.assertEqual(len({s.id for s in signals}), 1)
        self.assertEqual(Signal.objects.get().detail['who'], ['대표', '편집장'])

    def test_funding_posts_about_the_same_book_are_one_signal(self):
        self.post('1', text='『바람의 책』 북펀드에 함께해 주세요')
        self.post('2', account='ceo', text='다음 책 『바람의 책』 펀딩이 열렸어요, 많은 참여를')
        llm = FakeLLM({'items': [verdict(0, category='funding', books=['바람의 책']),
                                 verdict(1, category='funding', books=['바람의 책'])]})
        J.judge_pending(llm, NOW, LABELS)
        self.assertEqual(Signal.objects.get().detail['who'], ['편집장', '대표'])

    def test_llm_omission_leaves_post_pending(self):
        self.post('1', text='『농부, 짠한 형』')
        J.judge_pending(FakeLLM({'items': []}), NOW, LABELS)
        self.assertIsNone(SocialPost.objects.get().judged_at)

    def test_only_recent_posts_are_judged(self):
        self.post('1', text='옛 글', posted_at=NOW - timedelta(days=31))
        self.assertEqual(J.judge_pending(FakeLLM([]), NOW, LABELS), [])

    def test_site_link_links_book(self):
        self.post('1', text='책창고에서 보기', link={'url': f'https://hantijae-bookstore.com/book={self.farmer.id}',
                                                  'title': '책 소개', 'source': ''})
        [s] = J.judge_pending(FakeLLM({'items': [verdict(category='new_book')]}), NOW, LABELS)
        self.assertEqual(s.book, self.farmer)
