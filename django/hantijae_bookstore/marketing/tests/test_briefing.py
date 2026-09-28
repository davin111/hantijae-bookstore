from datetime import date, datetime, timedelta

from django.test import TestCase

from marketing.briefing import build_weekly, compose, measure_line, save_briefing
from marketing.candidates import Candidate
from marketing.models import Briefing, Draft, Proposal, SalesSnapshot, Signal
from marketing.tests.fakes import FakeLLM, make_book
from marketing.timeutil import KST
from web.models import StoreClick

TODAY = date(2026, 9, 28)


def item(cid, body='글', headline='『책』 ― 계기', reason='이유'):
    return {'candidate_id': cid, 'headline': headline, 'reason': reason,
            'draft': {'channel': 'instagram', 'title': '', 'body': body}}


class ComposeTest(TestCase):
    def setUp(self):
        self.a = make_book(title='시월, 곡비의 노래', isbn='979-11-00000-11-1', description='41편과 6편', author=None)
        self.b = make_book(title='내란 앞에서', isbn='979-11-00000-12-1', author=None)
        self.c = make_book(title='커밍아웃 스토리', isbn='979-11-00000-13-1', author=None)
        self.cands = [
            Candidate(id='hook:1', kind='hook', books=[self.a], summary='10월 1일 대구 10월항쟁', facts={}, urgency=3,
                      memorial=True),
            Candidate(id='fund:2', kind='fund', books=[], summary='목표의 135%(677만 원, 376권)', facts={}, urgency=3),
            Candidate(id='noreview:3', kind='noreview', books=[self.b], summary='리뷰 없음', facts={}, urgency=1),
            Candidate(id='hook:4', kind='hook', books=[self.b], summary='10월 11일', facts={}, urgency=2),
            Candidate(id='blog:5', kind='blog', books=[self.c], summary='블로그 없음', facts={}, urgency=1)]

    def test_compose_keeps_valid_items_in_order(self):
        llm = FakeLLM({'items': [item('hook:1', body='시 41편이 실렸습니다'), item('fund:2', body='376권이 모였습니다')]})
        items, dropped = compose(llm, self.cands, TODAY)
        self.assertEqual([i[0].id for i in items], ['hook:1', 'fund:2'])
        self.assertEqual(dropped, [])

    def test_compose_drops_unknown_id_and_invented_numbers(self):
        llm = FakeLLM({'items': [item('hook:99'), item('fund:2', body='벌써 500권이 모였어요')]})
        items, dropped = compose(llm, self.cands, TODAY)
        self.assertEqual(items, [])
        self.assertEqual(len(dropped), 2)

    def test_compose_drops_sales_push_on_memorial(self):
        llm = FakeLLM({'items': [item('hook:1', body='지금 서점에서 구매하세요')]})
        items, dropped = compose(llm, self.cands, TODAY)
        self.assertEqual(items, [])
        self.assertIn('추모', dropped[0])

    def test_compose_drops_same_book_twice_and_caps_three(self):
        llm = FakeLLM({'items': [item('noreview:3'), item('hook:4'), item('hook:1', body='소개'), item('fund:2'),
                                 item('blog:5')]})
        items, _ = compose(llm, self.cands, TODAY)
        self.assertEqual([i[0].id for i in items], ['noreview:3', 'hook:1', 'fund:2'])

    def test_compose_fixes_title_marks(self):
        llm = FakeLLM({'items': [item('blog:5', headline='『커밍아웃 스토리 ― 부모들의 이야기』')]})
        items, _ = compose(llm, self.cands, TODAY)
        self.assertEqual(items[0][1], '『커밍아웃 스토리』 ― 부모들의 이야기')

    def test_save_briefing_replaces_items_on_rebuild(self):
        cand = self.cands[2]
        save_briefing([(cand, 'h1', 'r', {'channel': 'instagram', 'title': '', 'body': 'b'})], TODAY)
        b = save_briefing([(cand, 'h2', 'r', {'channel': 'letter', 'title': 't', 'body': 'b2'})], TODAY)
        self.assertEqual(Briefing.objects.count(), 1)
        self.assertEqual(list(b.items.values_list('headline', flat=True)), ['h2'])
        self.assertEqual(Draft.objects.get(proposal__briefing=b).channel, Draft.LETTER)

    def test_rebuild_frees_signal_of_dropped_item(self):
        s = Signal.objects.create(kind=Signal.NEWS, key='k', book=self.b, title='칼럼', relevant=True)
        news = Candidate(id=f'news:{s.id}', kind='news', books=[self.b], summary='', facts={}, urgency=2, signal=s)
        save_briefing([(news, 'h1', 'r', {'channel': 'instagram', 'title': '', 'body': 'b'})], TODAY)
        s.refresh_from_db()
        self.assertIsNotNone(s.used_at)
        save_briefing([(self.cands[4], 'h2', 'r', {'channel': 'instagram', 'title': '', 'body': 'b'})], TODAY)
        s.refresh_from_db()
        self.assertIsNone(s.used_at)


class MeasureTest(TestCase):
    def test_measure_line_compares_posting_day_and_two_weeks_later(self):
        book = make_book()
        p = Proposal.objects.create(kind=Proposal.KIT, book=book, headline='x')
        posted = datetime(2026, 9, 10, 10, 0, tzinfo=KST)
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='b', status=Draft.POSTED, posted_at=posted)
        SalesSnapshot.objects.create(book=book, date=date(2026, 9, 10), sales_point=455)
        SalesSnapshot.objects.create(book=book, date=date(2026, 9, 25), sales_point=520)
        self.assertEqual(measure_line(TODAY),
                         '지난번 올린 『나는 산속으로 더 깊이 들어간다』 인스타 글 ― 판매 지수 455 → 520 (2주 뒤)')

    def test_measure_line_empty_before_two_weeks(self):
        book = make_book()
        p = Proposal.objects.create(kind=Proposal.KIT, book=book, headline='x')
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='b', status=Draft.POSTED,
                             posted_at=datetime(2026, 9, 20, 10, 0, tzinfo=KST))
        self.assertEqual(measure_line(TODAY), '')

    def test_measure_line_adds_store_clicks_within_two_weeks(self):
        book = make_book()
        p = Proposal.objects.create(kind=Proposal.KIT, book=book, headline='x')
        posted = datetime(2026, 9, 10, 10, 0, tzinfo=KST)
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='b', status=Draft.POSTED, posted_at=posted)
        SalesSnapshot.objects.create(book=book, date=date(2026, 9, 10), sales_point=455)
        SalesSnapshot.objects.create(book=book, date=date(2026, 9, 25), sales_point=520)
        window_start = datetime.combine(date(2026, 9, 10), datetime.min.time(), tzinfo=KST)
        inside_times = [window_start, window_start + timedelta(days=7), window_start + timedelta(days=13)]
        outside_time = window_start + timedelta(days=14)
        for t in inside_times:
            c = StoreClick.objects.create(book=book, store='aladin')
            StoreClick.objects.filter(pk=c.pk).update(created_at=t)
        c = StoreClick.objects.create(book=book, store='aladin')
        StoreClick.objects.filter(pk=c.pk).update(created_at=outside_time)
        self.assertTrue(measure_line(TODAY).endswith('(2주 뒤), 사이트 서점 버튼 3번'))


class BuildWeeklyTest(TestCase):
    def test_build_weekly_marks_signal_used(self):
        book = make_book(title='무지개를 변호하다', published=date(2026, 6, 1), isbn='979-11-00000-14-1')
        s = Signal.objects.create(kind=Signal.NEWS, key='k', book=book, title='칼럼', relevant=True, happens_on=TODAY,
                                  detail={'source': '법률신문', 'summary': '칼럼'})
        now = datetime(2026, 9, 28, 7, 0, tzinfo=KST)
        llm = FakeLLM({'items': [item(f'news:{s.id}', headline='『무지개를 변호하다』 ― 칼럼')]})
        b, dropped = build_weekly(llm, TODAY, now, posts=[])
        self.assertEqual(b.items.count(), 1)
        s.refresh_from_db()
        self.assertIsNotNone(s.used_at)

    def test_rebuilding_same_week_keeps_the_same_items(self):
        blog_book = make_book(title='시월, 곡비의 노래', published=date(2026, 9, 1), isbn='979-11-00000-15-1', author=None)
        news_book = make_book(title='무지개를 변호하다', published=date(2026, 6, 1), isbn='979-11-00000-14-1', author=None)
        s = Signal.objects.create(kind=Signal.NEWS, key='k', book=news_book, title='칼럼', relevant=True, happens_on=TODAY,
                                  detail={'source': '법률신문', 'summary': '칼럼'})
        now = datetime(2026, 9, 28, 7, 0, tzinfo=KST)
        llm = FakeLLM({'items': [item(f'blog:{blog_book.id}', headline='『시월, 곡비의 노래』 ― 블로그 글'),
                                 item(f'news:{s.id}', headline='『무지개를 변호하다』 ― 칼럼')]})
        keys = []
        for _ in range(3):  # 예전에는 두 번째에 비고 세 번째에 다시 찼다
            b, _ = build_weekly(llm, TODAY, now, posts=[])
            keys.append(list(b.items.order_by('rank').values_list('candidate_key', flat=True)))
        self.assertEqual(keys[0], [f'blog:{blog_book.id}', f'news:{s.id}'])
        self.assertEqual(keys[1:], [keys[0], keys[0]])
        self.assertEqual(len(llm.calls), 3)
        s.refresh_from_db()
        self.assertIsNotNone(s.used_at)
