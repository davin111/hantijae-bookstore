from datetime import date, datetime, timedelta

from django.test import TestCase

from marketing import placements as P
from marketing.meta import OfficialPost
from marketing.models import Draft, Proposal, SocialPost
from marketing.tests.fakes import make_book
from marketing.timeutil import KST
from web.blog import BlogPost

POSTED = datetime(2026, 9, 30, 14, 48, tzinfo=KST)
BODY = ('굴삭기를 몰고 농사일을 도우면서 통기타를 놓지 않는 가수가 있습니다.\n\n'
        "EBS 〈한국기행〉 '박강수의 두 번째 무대'가 EBS다큐 유튜브에 올라왔습니다.")
LABELS = {'editor': '편집장', 'ceo': '대표'}


def social(n, text, at, platform='facebook', account='editor', cleared=False):
    return SocialPost.objects.create(platform=platform, account=account, post_id=f'p{n}', url=f'https://fb/{n}',
                                     posted_at=at, text=text, first_seen=at, last_seen=at,
                                     text_cleared_at=at if cleared else None)


class FindTest(TestCase):
    def setUp(self):
        self.book = make_book(title='그리운 바람이 나를 불러', subtitle='박강수 노래시집', isbn='979-11-92455-82-2',
                              author='박강수')
        p = Proposal.objects.create(kind=Proposal.NOW, book=self.book, headline='h')
        self.draft = Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body=BODY, status=Draft.POSTED,
                                          posted_at=POSTED)

    def test_official_page_post_found_by_similar_text(self):
        fb = OfficialPost('facebook', POSTED - timedelta(minutes=6), BODY.replace('도우면서', '도우면서도'),
                          'https://f/p', id='111_9')
        found = P.find(self.draft, {'facebook': [fb], 'instagram': []}, [], [], LABELS)
        self.assertEqual(found, [{'kind': 'facebook', 'label': '한티재 페북 페이지', 'url': 'https://f/p', 'id': '111_9',
                                  'at': fb.posted_at.isoformat()}])

    def test_personal_post_found_by_book_title(self):
        sp = social(1, '박강수 님 영상이 화제네요. 노래시집 『그리운 바람이 나를 불러』도 함께.', POSTED + timedelta(hours=1))
        found = P.find(self.draft, {'facebook': None, 'instagram': None}, [sp], [], LABELS)
        self.assertEqual([(f['kind'], f['label'], f['url']) for f in found],
                         [('personal', '편집장님 페이스북', 'https://fb/1')])

    def test_blog_post_found_by_title_within_days(self):
        blog = [BlogPost('박강수의 두 번째 무대, 그리고 『그리운 바람이 나를 불러』', 'https://b/1', date(2026, 10, 1), '한티재의 책'),
                BlogPost('『그리운 바람이 나를 불러』 출간', 'https://b/0', date(2026, 2, 10), '한티재의 책')]
        found = P.find(self.draft, {'facebook': None, 'instagram': None}, [], blog, LABELS)
        self.assertEqual([(f['kind'], f['label'], f['url']) for f in found], [('blog', '네이버 블로그', 'https://b/1')])

    def test_ignores_other_books_other_days_and_cleared_text(self):
        far = OfficialPost('facebook', POSTED + timedelta(days=5), BODY, 'https://f/late', id='111_10')
        other = OfficialPost('instagram', POSTED, '『무지개를 변호하다』 북토크 안내', 'https://i/1', id='222_1')
        cleared = social(2, '', POSTED, cleared=True)
        unknown_role = social(3, '『그리운 바람이 나를 불러』', POSTED, platform='instagram', account='guest')
        found = P.find(self.draft, {'facebook': [far], 'instagram': [other]}, [cleared, unknown_role], [], LABELS)
        self.assertEqual([(f['kind'], f['label']) for f in found], [('personal', '운영진 인스타그램')])


class UpdateRecentTest(TestCase):
    def setUp(self):
        book = make_book(title='그리운 바람이 나를 불러', isbn='979-11-92455-82-2', author='박강수')
        p = Proposal.objects.create(kind=Proposal.NOW, book=book, headline='h')
        self.draft = Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body=BODY, status=Draft.POSTED,
                                          posted_at=POSTED)
        self.calls = []

    def official(self, since):
        self.calls.append(since)
        return {'facebook': [OfficialPost('facebook', POSTED - timedelta(minutes=6), BODY, 'https://f/p', id='111_9')],
                'instagram': None}

    def test_records_places_once_and_only_for_recent_posts(self):
        now = POSTED + timedelta(days=1)
        self.assertEqual(P.update_recent(now, official_posts=self.official, blog_posts=lambda: None, labels=LABELS), 1)
        self.assertEqual(self.calls, [POSTED - timedelta(days=P.BEFORE_DAYS)])
        self.assertEqual(P.update_recent(now, official_posts=self.official, blog_posts=lambda: None, labels=LABELS), 0)
        self.draft.refresh_from_db()
        self.assertEqual([f['label'] for f in self.draft.placements], ['한티재 페북 페이지'])

    def test_later_find_is_added_to_earlier_places(self):
        now = POSTED + timedelta(days=1)
        P.update_recent(now, official_posts=self.official, blog_posts=lambda: None, labels=LABELS)
        social(1, '『그리운 바람이 나를 불러』 영상', POSTED + timedelta(hours=2))
        self.assertEqual(P.update_recent(now + timedelta(days=1), official_posts=self.official, blog_posts=lambda: None,
                                         labels=LABELS), 1)
        self.draft.refresh_from_db()
        self.assertEqual([f['label'] for f in self.draft.placements], ['한티재 페북 페이지', '편집장님 페이스북'])

    def test_nothing_recent_makes_no_request(self):
        blog_calls = []
        now = POSTED + timedelta(days=P.LOOK_DAYS + 1)
        self.assertEqual(P.update_recent(now, official_posts=self.official, blog_posts=lambda: blog_calls.append(1),
                                         labels=LABELS), 0)
        self.assertEqual((self.calls, blog_calls), ([], []))
