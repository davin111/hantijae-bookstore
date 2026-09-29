from datetime import date, datetime, timedelta
from types import SimpleNamespace

from django.test import TestCase

from intake.models import FundingCampaign
from marketing import candidates as C
from marketing.hooks import seed
from marketing.models import BookProfile, Briefing, FundingSnapshot, Proposal, SalesSnapshot, Signal
from marketing.tests.fakes import make_book
from marketing.timeutil import KST
from web.models import Notice

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

    def test_selection_candidate_is_urgent_and_carries_label(self):
        notice = Notice.objects.create(message='x', state=Notice.POSTED)
        s = Signal.objects.create(kind=Signal.SELECTION, key=f'selection:kpipa:2145:{self.naeran.id}', book=self.naeran,
                                  title='2026년 세종도서 교양부문', url='https://www.kpipa.or.kr/p/g1_2/2145',
                                  happens_on=date(2026, 8, 25), detail={'notice_id': notice.id}, relevant=True)
        c = C.selection_candidates(NOW)[0]
        self.assertEqual((c.id, c.kind, c.urgency, c.signal), (f'selection:{s.id}', 'selection', 3, s))
        self.assertEqual(c.summary, '2026년 세종도서 교양부문 선정 ― 첫 화면 알림이 떠 있음')
        self.assertEqual(C.KIND_LABEL['selection'], '공공 선정')
        self.assertIn(f'selection:{s.id}', [x.id for x in C.gather(TODAY, NOW, posts=[])])

    def test_irrelevant_selection_signal_is_not_a_candidate(self):
        Signal.objects.create(kind=Signal.SELECTION, key='selection:old', book=self.naeran, title='2019년 세종도서',
                              relevant=False)
        self.assertEqual(C.selection_candidates(NOW), [])

    def test_selection_with_draft_or_removed_notice_is_not_a_candidate(self):
        draft = Notice.objects.create(message='x', state=Notice.DRAFT)
        removed = Notice.objects.create(message='x', state=Notice.REMOVED)
        Signal.objects.create(kind=Signal.SELECTION, key='selection:kpipa:10', book=self.naeran,
                              title='2026년 세종도서 교양부문', relevant=True, detail={'notice_id': draft.id})
        Signal.objects.create(kind=Signal.SELECTION, key='selection:kpipa:11', book=self.naeran,
                              title='2026년 문학나눔', relevant=True, detail={'notice_id': removed.id})
        Signal.objects.create(kind=Signal.SELECTION, key='selection:kpipa:12', book=self.naeran,
                              title='2026년 우수학술도서', relevant=True, detail={})
        self.assertEqual(C.selection_candidates(NOW), [])

    def test_selection_used_by_an_earlier_week_is_not_proposed_again(self):
        """한 번 브리핑에 쓴 선정은 다음 주에 다시 제안하지 않는다(NEEDS_REST가 아니므로 used_at이 막는다)."""
        notice = Notice.objects.create(message='x', state=Notice.POSTED)
        s = Signal.objects.create(kind=Signal.SELECTION, key='selection:kpipa:1', book=self.naeran,
                                  title='2026년 세종도서 교양부문', relevant=True, used_at=NOW - timedelta(days=7),
                                  detail={'notice_id': notice.id})
        last_week = Briefing.objects.create(week_start=date(2026, 9, 21))
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, briefing=last_week, signal=s, headline='h')
        self.assertEqual(C.selection_candidates(NOW), [])

    def test_selection_used_by_this_weeks_briefing_stays_a_candidate(self):
        """같은 주 브리핑을 다시 만들 때(gather가 save_briefing보다 먼저 돈다) 선정 항목이 빠지지 않게."""
        notice = Notice.objects.create(message='x', state=Notice.POSTED)
        s = Signal.objects.create(kind=Signal.SELECTION, key='selection:kpipa:2', book=self.naeran,
                                  title='2026년 세종도서 교양부문', relevant=True, used_at=NOW,
                                  detail={'notice_id': notice.id})
        this_week = Briefing.objects.create(week_start=date(2026, 9, 28))
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, briefing=this_week, signal=s, headline='h')
        self.assertEqual([c.id for c in C.selection_candidates(NOW)], [f'selection:{s.id}'])
