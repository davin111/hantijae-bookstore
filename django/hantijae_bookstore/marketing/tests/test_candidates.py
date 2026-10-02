import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from intake.models import FundingCampaign, WorkerState
from marketing import candidates as C
from marketing.hooks import seed
from marketing.models import BookProfile, Briefing, FundingSnapshot, LoanSnapshot, Proposal, SalesSnapshot, Signal
from marketing.tests.fakes import make_book, make_sale
from marketing.timeutil import KST
from web.models import Notice

TODAY = date(2026, 9, 28)
NOW = datetime(2026, 9, 28, 7, 0, tzinfo=KST)


def review(book, n, source='naver_blog', where='', day=date(2026, 9, 25), used_at=None):
    return Signal.objects.create(kind=Signal.REVIEW, key=f'review:{book.id}:{n}', book=book, title=f'서평 {n}',
                                 url=f'https://blog.naver.com/r/{n}', happens_on=day, relevant=True, used_at=used_at,
                                 detail={'source': source, 'where': where, 'verdict': 'review'})


def loans_of(book, *pairs):
    for month, n in pairs:
        LoanSnapshot.objects.create(book=book, month=month, loans=n)


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
        self.assertEqual(c.link, 'u')  # 브리핑 메시지에 '펀딩 페이지'로 붙는다
        self.assertNotIn('u', c.as_prompt()['facts'].values())  # 링크는 LLM에 보내지 않는다(글에 주소를 넣지 않게)

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
                              happens_on=TODAY, detail={'source': '한겨레', 'summary': '강연'},
                              url='https://news.example/a')
        Signal.objects.create(kind=Signal.NEWS, key='b', book=self.naeran, title='부고', relevant=True, sensitive=True,
                              happens_on=TODAY)
        self.assertEqual([(c.signal.title, c.link) for c in C.news_candidates(NOW)], [('좋은 소식', 'https://news.example/a')])

    def test_select_passes_twenty_candidates_to_the_llm(self):
        """12개면 기념일·계기·저자 칼럼이 자리를 다 채워 운영진 SNS 후보가 LLM에 가지도 못했다(2026-09-30)."""
        cands = [C.Candidate(id=f'hook:{i}', kind='hook', books=[self.naeran], summary='', facts={}, urgency=2)
                 for i in range(25)]
        self.assertEqual(len(C.select(cands, TODAY, NOW)), 20)

    def test_select_logs_ids_dropped_by_the_cap(self):
        cands = [C.Candidate(id=f'hook:{i}', kind='hook', books=[self.naeran], summary='', facts={}, urgency=2)
                 for i in range(25)]
        with self.assertLogs('intake', 'INFO') as cm:
            kept = C.select(cands, TODAY, NOW)
        self.assertEqual(len(kept), 20)
        logged = '\n'.join(cm.output)
        for c in cands[20:]:
            self.assertIn(c.id, logged)

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

    def test_review_candidate_groups_a_books_new_reviews(self):
        rs = [review(self.sibwol, 1, day=date(2026, 9, 20)), review(self.sibwol, 2, day=date(2026, 9, 26)),
              review(self.sibwol, 3, day=date(2026, 9, 22)),
              review(self.sibwol, 4, source='daum_cafe', where='시읽는모임', day=date(2026, 9, 24))]
        [c] = C.review_candidates(TODAY, NOW)
        self.assertEqual((c.id, c.kind, c.urgency, c.books), (f'review:{self.sibwol.id}:2026-09-28', 'review', 2, [self.sibwol]))
        self.assertEqual(c.summary, '새 독자 서평 4건(네이버 블로그 3, 다음 카페 1)')
        self.assertEqual(c.link, '\n'.join(r.url for r in (rs[1], rs[3], rs[2])))   # 최근 것부터 3개
        self.assertEqual((c.signal, set(c.more_signals)), (rs[1], {rs[0], rs[2], rs[3]}))
        self.assertEqual(c.facts['items'][1], {'where': '다음 카페 「시읽는모임」', 'date': '2026-09-24', 'title': '서평 4'})
        self.assertNotIn('http', json.dumps(c.as_prompt(), ensure_ascii=False))   # 주소는 LLM에 보내지 않는다
        self.assertEqual((C.KIND_LABEL['review'], C.LINK_LABEL['review']), ('새 독자 서평', '서평 글'))

    def test_review_candidate_summary_for_web_or_youtube_mentions(self):
        """기사·영상(출처 web·youtube)이 섞이면 '새 독자 서평'이 아니라 '새 서평·언급'으로 쓴다(F1).
        KIND_LABEL['review']는 그대로 '새 독자 서평'이다(briefing.py의 다른 쓰임이 바뀌면 안 되므로)."""
        review(self.sibwol, 1, source='web')
        [c] = C.review_candidates(TODAY, NOW)
        self.assertEqual(c.summary, '새 서평·언급 1건(웹 언급 1)')
        self.assertEqual(C.KIND_LABEL['review'], '새 독자 서평')

    def test_review_candidate_notes_missing_aladin_reviews(self):
        SalesSnapshot.objects.create(book=self.sibwol, date=TODAY, sales_point=50, short_reviews=0, reviews=0)
        review(self.sibwol, 1)
        [c] = C.review_candidates(TODAY, NOW)
        self.assertTrue(c.summary.endswith(' ― 알라딘 리뷰·100자평은 아직 없음'))
        self.assertEqual(c.facts['aladin_reviews'], 0)

    def test_old_used_or_irrelevant_reviews_are_not_candidates(self):
        review(self.sibwol, 1, used_at=NOW - timedelta(days=7))   # 지난주 브리핑에 씀
        old = review(self.naeran, 2)
        Signal.objects.filter(pk=old.pk).update(found_at=NOW - timedelta(days=15))
        Signal.objects.create(kind=Signal.REVIEW, key='review:x', book=self.naeran, title='홍보', relevant=False,
                              detail={'source': 'naver_blog', 'verdict': 'promo'})
        self.assertEqual(C.review_candidates(TODAY, NOW), [])

    def test_reviews_used_by_this_weeks_briefing_stay_candidates(self):
        a, b = review(self.sibwol, 1, used_at=NOW), review(self.sibwol, 2, used_at=NOW)
        this_week = Briefing.objects.create(week_start=date(2026, 9, 28))
        Proposal.objects.create(kind=Proposal.BRIEF_ITEM, briefing=this_week, signal=a, headline='h',
                                extra={'signals': [b.id]})
        [c] = C.review_candidates(TODAY, NOW)
        self.assertEqual({c.signal} | set(c.more_signals), {a, b})

    def test_gather_drops_noreview_for_a_book_with_new_reviews(self):
        SalesSnapshot.objects.create(book=self.sibwol, date=TODAY, sales_point=50, short_reviews=0, reviews=0)
        SalesSnapshot.objects.create(book=self.naeran, date=TODAY, sales_point=50, short_reviews=0, reviews=0)
        review(self.sibwol, 1)
        ids = [c.id for c in C.gather(TODAY, NOW, posts=None)]
        self.assertIn(f'review:{self.sibwol.id}:2026-09-28', ids)
        self.assertNotIn(f'noreview:{self.sibwol.id}', ids)
        self.assertIn(f'noreview:{self.naeran.id}', ids)

    def test_review_candidates_keep_the_five_busiest_books(self):
        books = [self.sibwol, self.naeran] + [make_book(title=f'책 {i}', isbn=f'979-11-00050-{i:02d}-0', author=None)
                                              for i in range(5)]
        for i, book in enumerate(books):
            for n in range(i + 1):
                review(book, n)
        cands = C.review_candidates(TODAY, NOW)
        self.assertEqual([c.facts['count'] for c in cands], [7, 6, 5, 4, 3])
        self.assertEqual([c.books[0] for c in cands], [books[6], books[5], books[4], books[3], books[2]])

    def test_gather_puts_sns_before_reviews(self):
        review(self.sibwol, 1)
        # merge_fund_posts는 sns_repost 후보의 signal.detail을 본다(실제로는 늘 있다) → 최소한의 흉내만 준다
        sns = [C.Candidate(id='sns:1', kind='sns_repost', books=[self.naeran], summary='s', facts={}, urgency=2,
                           signal=SimpleNamespace(detail={}))]
        with mock.patch('marketing.candidates.social_candidates', return_value=sns):
            ids = [c.id for c in C.gather(TODAY, NOW, posts=None)]
        self.assertLess(ids.index('sns:1'), ids.index(f'review:{self.sibwol.id}:2026-09-28'))

    def test_gather_keeps_loan_among_many_noreview_candidates(self):
        """cap(20)이 상시 후보(리뷰 없음)부터 잘리므로 도서관 대출 후보가 살아남는다(gather의 순서, F1)."""
        books = [make_book(title=f'적립 {i}', isbn=f'979-11-00060-{i:02d}-0', author=None) for i in range(25)]
        noreview = [C.Candidate(id=f'noreview:{b.id}', kind='noreview', books=[b], summary='', facts={}, urgency=1)
                    for b in books]
        loan_book = make_book(title='대출 늘어난 책', isbn='979-11-00070-00-0', author=None)
        loan = [C.Candidate(id=f'loan:{loan_book.id}', kind='loan', books=[loan_book], summary='', facts={}, urgency=1)]
        with mock.patch('marketing.candidates.hook_candidates', return_value=[]), \
                mock.patch('marketing.candidates.funding_candidates', return_value=[]), \
                mock.patch('marketing.candidates.news_candidates', return_value=[]), \
                mock.patch('marketing.candidates.selection_candidates', return_value=[]), \
                mock.patch('marketing.candidates.social_candidates', return_value=[]), \
                mock.patch('marketing.candidates.review_candidates', return_value=[]), \
                mock.patch('marketing.candidates.surge_candidates', return_value=[]), \
                mock.patch('marketing.candidates.blog_gap_candidates', return_value=[]), \
                mock.patch('marketing.candidates.noreview_candidates', return_value=noreview), \
                mock.patch('marketing.candidates.loan_candidates', return_value=loan):
            result = C.gather(TODAY, NOW, posts=None)
        self.assertIn('loan', [c.kind for c in result])
        self.assertEqual(len(result), 20)

    def test_instagram_reviews_are_counted_and_named(self):
        review(self.sibwol, 1)
        review(self.sibwol, 2, source='ig_tag', where='@hagobooks', day=date(2026, 9, 26))
        [c] = C.review_candidates(TODAY, NOW)
        self.assertEqual(c.summary, '새 독자 서평 2건(네이버 블로그 1, 인스타 태그 1)')
        self.assertEqual(c.facts['items'][0]['where'], '인스타 태그 「@hagobooks」')

    def test_loan_candidate_for_steady_old_book(self):
        old = make_book(title='커밍아웃 스토리', published=date(2018, 6, 11), isbn='979-11-00000-31-1', author=None)
        loans_of(old, (date(2026, 6, 1), 20), (date(2026, 7, 1), 22), (date(2026, 8, 1), 30))
        [c] = C.loan_candidates(TODAY)
        self.assertEqual((c.id, c.kind, c.urgency, c.books), (f'loan:{old.id}:2026-08-01', 'loan', 1, [old]))
        # 정보나루가 빼고 준 달은 0회로 치므로 11달로 나눈다: round(42 / 11) = 4
        self.assertEqual(c.summary, '8월 도서관 대출 30회(앞선 11달 평균 4회)')
        self.assertEqual(c.facts, {'month': '2026-08', 'loans': 30, 'avg': 4})
        self.assertEqual(C.KIND_LABEL['loan'], '도서관 대출')

    def test_declining_new_or_hidden_books_are_not_candidates(self):
        down = make_book(title='줄어드는 책', published=date(2019, 1, 1), isbn='979-11-00000-32-8', author=None)
        down_months = [date(2025, 9, 1), date(2025, 10, 1), date(2025, 11, 1), date(2025, 12, 1),
                      date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1),
                      date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1)]   # 앞선 11달, 매달 20회
        loans_of(down, *[(m, 20) for m in down_months], (date(2026, 8, 1), 12))   # 평균 20인데 12 → 줄었다
        loans_of(self.sibwol, (date(2026, 8, 1), 90))            # 2026-06 출간 — 1년이 안 됨
        hidden = make_book(title='숨긴 책', published=date(2019, 1, 1), isbn='979-11-00000-33-5', author=None, visible=False)
        loans_of(hidden, (date(2026, 8, 1), 90))
        few = make_book(title='적은 책', published=date(2019, 1, 1), isbn='979-11-00000-34-2', author=None)
        loans_of(few, (date(2026, 8, 1), 9))
        self.assertEqual(C.loan_candidates(TODAY), [])

    def test_months_back(self):
        self.assertEqual(C._months_back(date(2026, 8, 1), 11), date(2025, 9, 1))
        self.assertEqual(C._months_back(date(2028, 2, 1), 11), date(2027, 3, 1))
        self.assertEqual(C._months_back(date(2026, 1, 1), 1), date(2025, 12, 1))

    def test_top_three_by_latest_loans(self):
        books = [make_book(title=f'책{i}', published=date(2019, 1, 1), isbn=f'979-11-00000-4{i}-0', author=None)
                 for i in range(5)]
        for i, b in enumerate(books):
            loans_of(b, (date(2026, 8, 1), 10 + i))
        self.assertEqual([c.books[0] for c in C.loan_candidates(TODAY)], [books[4], books[3], books[2]])

    def test_loan_is_rested(self):
        self.assertIn('loan', C.NEEDS_REST)


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


class MomentOrderTest(TestCase):
    def test_moments_survive_the_candidate_cap_among_equal_urgency(self):
        books = [make_book(title=f'책 {i}', isbn=f'979-11-00000-{i:02d}-0', author=None) for i in range(15)]
        base = [C.Candidate(id=f'news:{i}', kind='news', books=[books[i]], summary='소식', facts={}, urgency=2)
                for i in range(13)]
        moments = []
        for i in (13, 14):
            s = Signal.objects.create(kind=Signal.MOMENT, key=f'moment:{i}', book=books[i], title=f'계기 {i}',
                                      relevant=True, detail={'type': 'selection', 'status': 'done'})
            moments.append(C.Candidate(id=f'moment:{s.id}', kind='moment', books=[books[i]], summary='계기', facts={},
                                       urgency=2, signal=s))
        kept = C.select(C.with_moments(base, moments, NOW), TODAY, NOW, limit=12)
        self.assertEqual(len(kept), 12)
        self.assertEqual([c.kind for c in kept[:2]], ['moment', 'moment'])


class BnkSurgeTest(TestCase):
    def setUp(self):
        WorkerState.put('bnk_mode', 'on')
        self.naeran = make_book(title='내란 앞에서', published=date(2026, 7, 17), isbn='979-11-92455-89-1', author='김해원')
        SalesSnapshot.objects.create(book=self.naeran, date=TODAY - timedelta(days=7), sales_point=200)
        SalesSnapshot.objects.create(book=self.naeran, date=TODAY, sales_point=420)

    def test_surge_uses_bnk_sales_when_on(self):
        make_sale(date(2026, 9, 23), 8, book=self.naeran, yes24=7, kyobo=1)
        [s] = C.surge_candidates(TODAY)
        self.assertEqual((s.id, s.kind, s.books), (f'surge:{self.naeran.id}:2026-09-23', 'surge', [self.naeran]))
        self.assertEqual(s.summary, '최근 7일 8권 팔렸음(평소 주 0권), 예스24 7권')
        self.assertEqual(s.facts, {'week': 8, 'usual': '0',
                                   'stores': {'교보': 1, '예스24': 7, '알라딘': 0, '영풍': 0, '지역서점': 0}})

    def test_surge_falls_back_to_aladin_without_fresh_bnk_rows(self):
        make_sale(date(2026, 9, 1), 8, book=self.naeran)   # 10일 넘게 지난 기록뿐
        [s] = C.surge_candidates(TODAY)
        self.assertEqual(s.facts, {'before': 200, 'after': 420})
