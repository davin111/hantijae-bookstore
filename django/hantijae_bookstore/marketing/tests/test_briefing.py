from datetime import date, datetime, timedelta

from django.test import TestCase

from marketing.briefing import build_weekly, compose, measure_line, save_briefing
from marketing.candidates import Candidate
from marketing.models import Briefing, Draft, Proposal, SalesSnapshot, Signal
from marketing.tests.fakes import FakeLLM, make_book
from marketing.timeutil import KST
from web.models import Notice, StoreClick

TODAY = date(2026, 9, 28)


def item(cid, body='글', headline='『책』 ― 계기', reason='이유', title=''):
    return {'candidate_id': cid, 'headline': headline, 'reason': reason,
            'draft': {'channel': 'instagram', 'title': title, 'body': body}}


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

    def test_compose_drops_sales_push_in_memorial_headline_or_draft_title(self):
        llm = FakeLLM([{'items': [item('hook:1', headline='『시월, 곡비의 노래』 ― 서점에서 만나요', body='소개')]},
                       {'items': [item('hook:1', title='지금 구매하세요', body='소개')]}])
        for _ in range(2):
            items, dropped = compose(llm, self.cands, TODAY)
            self.assertEqual(items, [])
            self.assertIn('추모', dropped[0])

    def test_compose_keeps_memorial_item_when_only_the_reason_mentions_sales_words(self):
        """reason은 운영진에게 하는 말이라 게시되지 않는다. '구매 링크는 붙이지 않았다'는 설명 때문에 항목을 버리지 않고,
        판매 낱말이 든 문장만 뺀다(2026-09-30 10월항쟁 항목이 이 설명 때문에 두 번 버려졌다)."""
        llm = FakeLLM([{'items': [item('hook:1', body='소개', reason='내일이 10월항쟁이 일어난 날이라 글을 준비했습니다. '
                                                                 '추모의 날이라 구매 링크와 가격은 붙이지 않고 알리기만 했어요.')]},
                       {'items': [item('hook:1', body='소개', reason='지금 할인 중이라 알리면 좋아요.')]}])
        items, dropped = compose(llm, self.cands, TODAY)
        self.assertEqual((len(items), dropped), (1, []))
        self.assertEqual(items[0][2], '내일이 10월항쟁이 일어난 날이라 글을 준비했습니다.')
        items, dropped = compose(llm, self.cands, TODAY)
        self.assertEqual((len(items), dropped), (1, []))
        self.assertTrue(items[0][2])
        self.assertFalse(any(w in items[0][2] for w in ('할인', '구매', '링크')))

    def test_compose_drops_same_book_twice_and_caps_four(self):
        """주간 브리핑은 4개까지(2026-09-30 사용자 결정: 3개면 저자 소식이 계기·기념일·펀딩에 밀려 빠졌다)."""
        d = make_book(title='무지개를 변호하다', isbn='979-11-00000-14-1', author=None)
        cands = self.cands + [Candidate(id='news:6', kind='news', books=[d], summary='강연', facts={}, urgency=2)]
        llm = FakeLLM({'items': [item('noreview:3'), item('hook:4'), item('hook:1', body='소개'), item('fund:2'),
                                 item('blog:5'), item('news:6')]})
        items, _ = compose(llm, cands, TODAY)
        self.assertEqual([i[0].id for i in items], ['noreview:3', 'hook:1', 'fund:2', 'blog:5'])

    def test_compose_puts_the_places_to_send_on_top_of_a_letter(self):
        """2026-09-30 사용자: 브리핑 편지에 '알리면 좋을 곳'이 어딘지 없었다."""
        raw = item('fund:2', body='안녕하세요. 도서출판 한티재입니다.')
        raw['draft'].update(channel='letter', to=['농업·생협 단체', '귀농·귀촌 모임', ''])
        items, _ = compose(FakeLLM({'items': [raw]}), self.cands, TODAY)
        self.assertEqual(items[0][3]['body'],
                         '알리면 좋을 곳\n· 농업·생협 단체\n· 귀농·귀촌 모임\n\n보낼 글\n안녕하세요. 도서출판 한티재입니다.')
        plain = item('fund:2', body='안녕하세요.')
        plain['draft']['channel'] = 'letter'
        items, _ = compose(FakeLLM({'items': [plain]}), self.cands, TODAY)
        self.assertEqual(items[0][3]['body'], '안녕하세요.')

    def test_compose_fixes_title_marks(self):
        llm = FakeLLM({'items': [item('blog:5', headline='『커밍아웃 스토리 ― 부모들의 이야기』')]})
        items, _ = compose(llm, self.cands, TODAY)
        self.assertEqual(items[0][1], '『커밍아웃 스토리』 ― 부모들의 이야기')

    def test_save_briefing_keeps_the_candidate_link_for_the_message(self):
        news = Candidate(id='news:7', kind='news', books=[self.b], summary='강연', facts={}, urgency=2,
                         link='https://news.example/a')
        fund = Candidate(id='fund:2', kind='fund', books=[], summary='펀딩', facts={}, urgency=3,
                         link='https://www.aladin.co.kr/shop/bookfund/3013')
        d = {'channel': 'instagram', 'title': '', 'body': 'b'}
        b = save_briefing([(news, 'h1', 'r', d), (fund, 'h2', 'r', d), (self.cands[2], 'h3', 'r', d)], TODAY)
        extras = [p.extra for p in b.items.order_by('rank')]
        self.assertEqual(extras[0], {'link': 'https://news.example/a', 'link_label': '기사 원문'})
        self.assertEqual(extras[1], {'link': 'https://www.aladin.co.kr/shop/bookfund/3013', 'link_label': '펀딩 페이지'})
        self.assertEqual(extras[2], {})

    def test_save_briefing_replaces_items_on_rebuild(self):
        cand = self.cands[2]
        save_briefing([(cand, 'h1', 'r', {'channel': 'instagram', 'title': '', 'body': 'b'})], TODAY)
        b = save_briefing([(cand, 'h2', 'r', {'channel': 'letter', 'title': 't', 'body': 'b2'})], TODAY)
        self.assertEqual(Briefing.objects.count(), 1)
        self.assertEqual(list(b.items.values_list('headline', flat=True)), ['h2'])
        self.assertEqual(Draft.objects.get(proposal__briefing=b).channel, Draft.LETTER)

    def test_failed_save_keeps_the_previous_items(self):
        cand = self.cands[2]
        save_briefing([(cand, 'h1', 'r', {'channel': 'instagram', 'title': '', 'body': 'b'})], TODAY)
        with self.assertRaises(KeyError):
            save_briefing([(self.cands[4], 'h2', 'r', {'channel': 'instagram', 'title': '', 'body': 'b'}),
                           (cand, 'h3', 'r', {'title': '', 'body': 'b'})], TODAY)
        self.assertEqual(list(Proposal.objects.values_list('headline', flat=True)), ['h1'])

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

    def test_build_weekly_clips_long_measure_line(self):
        book = make_book(title='가' * 400)
        p = Proposal.objects.create(kind=Proposal.KIT, book=book, headline='x')
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='b', status=Draft.POSTED,
                             posted_at=datetime(2026, 9, 10, 10, 0, tzinfo=KST))
        SalesSnapshot.objects.create(book=book, date=date(2026, 9, 10), sales_point=455)
        SalesSnapshot.objects.create(book=book, date=date(2026, 9, 25), sales_point=520)
        b, _ = build_weekly(FakeLLM({'items': []}), TODAY, datetime(2026, 9, 28, 7, 0, tzinfo=KST), posts=[])
        self.assertEqual(len(b.measure), 300)

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

    def test_build_weekly_turns_google_news_links_into_publisher_links(self):
        book = make_book(title='무지개를 변호하다', published=date(2026, 6, 1), isbn='979-11-00000-14-1')
        s = Signal.objects.create(kind=Signal.NEWS, key='k', book=book, title='강연', relevant=True, happens_on=TODAY,
                                  detail={'source': '여성신문', 'summary': '강연'},
                                  url='https://news.google.com/rss/articles/CBMiABC?oc=5')
        llm = FakeLLM({'items': [item(f'news:{s.id}', headline='『무지개를 변호하다』 ― 강연')]})
        seen = []

        def resolve(url):
            seen.append(url)
            return 'https://www.womennews.co.kr/news/articleView.html?idxno=1'
        b, _ = build_weekly(llm, TODAY, datetime(2026, 9, 28, 7, 0, tzinfo=KST), posts=[], resolve=resolve)
        self.assertEqual(b.items.get().extra['link'], 'https://www.womennews.co.kr/news/articleView.html?idxno=1')
        self.assertEqual(seen, ['https://news.google.com/rss/articles/CBMiABC?oc=5'])  # 고른 항목의 링크만 바꾼다

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

    def test_rebuilding_same_week_keeps_the_selection_item(self):
        book = make_book(title='무궁화호를 위하여', published=date(2026, 3, 16), isbn='979-11-00000-16-1', author=None)
        notice = Notice.objects.create(message='x', state=Notice.POSTED)
        s = Signal.objects.create(kind=Signal.SELECTION, key='selection:kpipa:2145', book=book,
                                  title='2026년 세종도서 교양부문', relevant=True, happens_on=date(2026, 8, 25),
                                  detail={'notice_id': notice.id})
        now = datetime(2026, 9, 28, 7, 0, tzinfo=KST)
        llm = FakeLLM({'items': [item(f'selection:{s.id}', headline='『무궁화호를 위하여』 ― 2026년 세종도서 교양부문 선정')]})
        keys = []
        for _ in range(3):
            b, _ = build_weekly(llm, TODAY, now, posts=[])
            keys.append(list(b.items.values_list('candidate_key', flat=True)))
        self.assertEqual(keys, [[f'selection:{s.id}']] * 3)
        s.refresh_from_db()
        self.assertIsNotNone(s.used_at)

    def test_overlong_llm_headline_and_title_are_saved_clipped(self):
        book = make_book(title='무지개를 변호하다', published=date(2026, 6, 1), isbn='979-11-00000-14-1', author=None)
        long = '가' * 400
        llm = FakeLLM({'items': [{'candidate_id': f'blog:{book.id}', 'headline': long, 'reason': '이유',
                                  'draft': {'channel': 'blog', 'title': long, 'body': '글'}}]})
        b, _ = build_weekly(llm, TODAY, datetime(2026, 9, 28, 7, 0, tzinfo=KST), posts=[])
        p = b.items.get()
        self.assertEqual((len(p.headline), len(p.drafts.get().title)), (300, 300))
