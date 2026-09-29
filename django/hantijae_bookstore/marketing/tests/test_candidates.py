from datetime import date, datetime, timedelta
from types import SimpleNamespace

from django.test import TestCase

from intake.models import FundingCampaign
from marketing import candidates as C
from marketing.hooks import seed
from marketing.models import BookProfile, Briefing, FundingSnapshot, Proposal, SalesSnapshot, Signal
from marketing.tests.fakes import make_book
from marketing.timeutil import KST

TODAY = date(2026, 9, 28)
NOW = datetime(2026, 9, 28, 7, 0, tzinfo=KST)


class CandidateTest(TestCase):
    def setUp(self):
        self.sibwol = make_book(title='시월, 곡비의 노래', subtitle='10월문학회 시선집', published=date(2026, 6, 15),
                                isbn='979-11-92455-88-4', author='10월문학회', description='항쟁 80주년 41편')
        self.naeran = make_book(title='내란 앞에서', published=date(2026, 7, 17), isbn='979-11-92455-89-1',
                                author='김해원')

    def test_hook_candidate_carries_memorial_and_days_left(self):
        seed()
        hooks = C.hook_candidates(TODAY)
        c = next(x for x in hooks if x.id.startswith('hook:') and self.sibwol in x.books)
        self.assertTrue(c.memorial)
        self.assertEqual((c.facts['days_left'], c.urgency), (3, 3))

    def test_funding_candidate_uses_latest_snapshot(self):
        camp = FundingCampaign.objects.create(platform='aladin', external_id='3013', url='u', title='농부, 짠한 형',
                                              publisher='한티재', starts_at=NOW - timedelta(days=10),
                                              ends_at=datetime(2026, 10, 12, 0, 0, tzinfo=KST), is_ours=True)
        FundingSnapshot.objects.create(campaign=camp, date=TODAY, amount=6768000, goal=5000000, books=376)
        [c] = C.funding_candidates(TODAY, NOW)
        self.assertIn('목표의 135%(677만 원, 376권)', c.summary)
        self.assertEqual((c.facts['days_left'], c.urgency, c.books), (13, 2, []))

    def test_blog_gap_skipped_when_rss_failed(self):
        self.assertEqual(C.blog_gap_candidates(TODAY, None), [])
        gaps = C.blog_gap_candidates(TODAY, [SimpleNamespace(title='『내란 앞에서』 ― 한 헌법학자의 일지')])
        self.assertEqual([c.books for c in gaps], [[self.sibwol]])

    def test_noreview_and_surge(self):
        SalesSnapshot.objects.create(book=self.sibwol, date=TODAY, sales_point=180)
        SalesSnapshot.objects.create(book=self.naeran, date=TODAY - timedelta(days=7), sales_point=200)
        SalesSnapshot.objects.create(book=self.naeran, date=TODAY, sales_point=420, short_reviews=2)
        self.assertEqual([c.books[0] for c in C.noreview_candidates(TODAY)], [self.sibwol])
        [s] = C.surge_candidates(TODAY)
        self.assertEqual((s.books, s.facts), ([self.naeran], {'before': 200, 'after': 420}))

    def test_news_candidate_only_relevant_unused_not_sensitive(self):
        Signal.objects.create(kind=Signal.NEWS, key='a', book=self.naeran, title='좋은 소식', relevant=True,
                              happens_on=TODAY, detail={'source': '한겨레', 'summary': '강연'})
        Signal.objects.create(kind=Signal.NEWS, key='b', book=self.naeran, title='부고', relevant=True, sensitive=True,
                              happens_on=TODAY)
        self.assertEqual([c.signal.title for c in C.news_candidates(NOW)], ['좋은 소식'])

    def test_select_drops_quiet_books_and_recently_proposed(self):
        BookProfile.objects.create(book=self.sibwol, quiet_until=date(2026, 10, 31))
        last_week = Briefing.objects.create(week_start=date(2026, 9, 21), sent_at=NOW - timedelta(days=7))
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.naeran, briefing=last_week, headline='x')
        cands = [C.Candidate(id='blog:1', kind='blog', books=[self.sibwol], summary='', facts={}, urgency=1),
                 C.Candidate(id='noreview:2', kind='noreview', books=[self.naeran], summary='', facts={}, urgency=1),
                 C.Candidate(id='hook:3', kind='hook', books=[self.naeran], summary='', facts={}, urgency=3)]
        self.assertEqual([c.id for c in C.select(cands, TODAY, NOW)], ['hook:3'])

    def test_select_rest_ignores_unsent_and_this_weeks_briefings(self):
        unsent = Briefing.objects.create(week_start=date(2026, 9, 21))
        this_week = Briefing.objects.create(week_start=date(2026, 9, 28), sent_at=NOW)
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.naeran, briefing=unsent, headline='x')
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=self.sibwol, briefing=this_week, headline='x')
        cands = [C.Candidate(id='blog:1', kind='blog', books=[self.sibwol], summary='', facts={}, urgency=1),
                 C.Candidate(id='noreview:2', kind='noreview', books=[self.naeran], summary='', facts={}, urgency=1)]
        self.assertEqual([c.id for c in C.select(cands, TODAY, NOW)], ['blog:1', 'noreview:2'])

    def test_select_drops_fund_of_quiet_book_but_keeps_bookless_fund(self):
        BookProfile.objects.create(book=self.sibwol, quiet_until=date(2026, 10, 31))
        cands = [C.Candidate(id='fund:1', kind='fund', books=[self.sibwol], summary='', facts={}, urgency=3),
                 C.Candidate(id='fund:2', kind='fund', books=[], summary='', facts={}, urgency=3)]
        self.assertEqual([c.id for c in C.select(cands, TODAY, NOW)], ['fund:2'])

    def test_allowed_texts_include_book_description(self):
        c = C.Candidate(id='x', kind='hook', books=[self.sibwol], summary='10월 1일', facts={'n': 376}, urgency=1)
        self.assertTrue(any('41편' in t for t in c.allowed_texts()))
        self.assertEqual(c.as_prompt()['books'], ['『시월, 곡비의 노래』 10월문학회 시선집'])


class MomentCandidateTest(TestCase):
    def setUp(self):
        from intake.models import WorkerState
        WorkerState.put('moment_mode', 'live')
        self.book = make_book(title='내란 앞에서', published=date(2026, 7, 17), isbn='979-11-92455-89-1', author='김해원')

    def moment(self, title, day=None, found=None, **detail):
        s = Signal.objects.create(kind=Signal.MOMENT, key=f'moment:{title}', book=detail.pop('book', self.book),
                                  title=title, happens_on=day, relevant=detail.get('status') != 'cancelled',
                                  sensitive=detail.pop('sensitive', False),
                                  detail={'type': 'author', 'status': 'planned', 'summary': '요약',
                                          'book_ids': [self.book.id], **detail})
        if found:
            Signal.objects.filter(pk=s.pk).update(found_at=found)
        return s

    def ids(self):
        return [c.signal.title for c in C.moment_candidates(TODAY, NOW)]

    def test_date_window_and_recap(self):
        self.moment('앞으로 사흘', day=TODAY + timedelta(days=3))
        self.moment('22일 뒤', day=TODAY + timedelta(days=22))
        self.moment('어제 끝남', day=TODAY - timedelta(days=1))
        self.moment('8일 전', day=TODAY - timedelta(days=8))
        cands = {c.signal.title: c for c in C.moment_candidates(TODAY, NOW)}
        self.assertEqual(set(cands), {'앞으로 사흘', '어제 끝남'})
        near = cands['앞으로 사흘']
        self.assertEqual((near.kind, near.books, near.urgency, near.facts['days_left']), ('moment', [self.book], 3, 3))
        self.assertEqual(near.summary, '10월 1일 저자 활동: 앞으로 사흘 ― 요약')
        self.assertIn('끝난 일 — 후기 글 후보', cands['어제 끝남'].summary)

    def test_undated_windows_and_exclusions(self):
        self.moment('최근', found=NOW - timedelta(days=13))
        self.moment('오래됨', found=NOW - timedelta(days=15))
        self.moment('신간 예고', found=NOW - timedelta(days=25), type='upcoming')
        self.moment('취소', status='cancelled')
        self.moment('이미 올림', promoted=True)
        self.moment('민감', sensitive=True)
        self.moment('날짜 모름', date_unverified=True, date_text='10월 중순')
        self.assertEqual(set(self.ids()), {'최근', '신간 예고', '날짜 모름'})
        vague = next(c for c in C.moment_candidates(TODAY, NOW) if c.signal.title == '날짜 모름')
        self.assertIn('(날짜 확인 필요: 10월 중순)', vague.summary)

    def test_book_hint_is_matched_later(self):
        s = self.moment('예고', book=None, book_ids=[], book_hint='무궁화호를 위하여')
        self.assertEqual(self.ids(), [])
        later = make_book(title='무궁화호를 위하여', isbn='979-11-00000-99-1', author=None)
        self.assertEqual(self.ids(), ['예고'])
        s.refresh_from_db()
        self.assertEqual((s.book, s.detail['book_ids'], s.detail['book_hint']), (later, [later.id], ''))

    def test_only_in_live_mode(self):
        from intake.models import WorkerState
        self.moment('앞으로', day=TODAY + timedelta(days=3))
        self.assertIn('moment:', ' '.join(c.id for c in C.gather(TODAY, NOW, [])))
        WorkerState.put('moment_mode', 'admin_only')
        self.assertNotIn('moment:', ' '.join(c.id for c in C.gather(TODAY, NOW, [])))

    def test_overlaps_with_funding_selection_and_surge(self):
        fund = C.Candidate(id='fund:1', kind='fund', books=[self.book], summary='펀딩', facts={}, urgency=3)
        surge = C.Candidate(id='surge:1', kind='surge', books=[self.book], summary='판매 지수가 올랐음', facts={}, urgency=2)
        m_fund = self.moment('펀딩 오픈', type='funding')
        m_sel = self.moment('세종도서', type='selection')
        m_group = self.moment('단체 주문 200권', type='group')
        Signal.objects.create(kind='selection', key='sel:1', book=self.book, title='세종도서 선정')
        moments = [c for c in C.moment_candidates(TODAY, NOW)]
        out = C.with_moments([fund, surge], moments, NOW)
        self.assertEqual([c.id for c in out], ['fund:1', 'surge:1'])
        self.assertIn('방에서 나온 이야기: 단체 주문 200권', surge.summary)
        self.assertEqual((surge.facts['room'], surge.signal), ('단체 주문 200권', m_group))
        self.assertFalse({m_fund.id, m_sel.id} & {c.signal.id for c in out if c.signal})

    def test_undated_window_follows_seen_on_not_found_at(self):
        self.moment('7월 이야기', seen_on='2026-07-20')
        self.moment('어제 이야기', seen_on='2026-09-27', found=NOW - timedelta(days=40))
        self.assertEqual(self.ids(), ['어제 이야기'])
