from datetime import date, datetime, timedelta
from unittest import mock

from django.test import TestCase

from intake.models import FundingCampaign, ReviewItem
from marketing import monthly
from marketing.meta import OfficialPost
from marketing.models import BnkDay, Draft, FundingSnapshot, GrantCall, HookDate, Proposal, Signal
from marketing.messages import TEXT_LIMIT
from marketing.tests.fakes import FakeBnkClient, make_book, make_call, make_sale
from marketing.text import tg_len
from marketing.timeutil import KST
from web.blog import BlogPost

SEP, SEP_END, OCT = date(2026, 9, 1), date(2026, 9, 30), date(2026, 10, 1)
TOTALS = {'kyobo': 10, 'yes24': 28, 'aladin': 2, 'ypbooks': 1, 'local': 3, 'total': 44, 'pc': 20, 'mobile': 17,
          'offline': 7}
READERS = {'age': [('50대', 35.26), ('40대', 16.32), ('60대 이상', 15.79), ('30대', 15.26)], 'female': 61.05,
           'male': 37.37, 'region': [('경기', 73), ('서울', 32), ('충북', 14), ('대구', 8)], 'buyers': 190}


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=KST)


def signal(kind, title, found=None, **kw):
    s = Signal.objects.create(kind=kind, key=f'{kind}:{title}', title=title, relevant=kw.pop('relevant', True), **kw)
    Signal.objects.filter(pk=s.pk).update(found_at=found or at(9, 10))
    return s


class Books(TestCase):
    def setUp(self):
        self.bap = make_book(title='밥은 먹고 다니냐는 말', subtitle='', published=date(2021, 10, 18),
                             isbn='979-11-90178-71-6', author='정은정')
        self.rainbow = make_book(title='무지개를 변호하다', subtitle='', published=date(2026, 6, 1),
                                 isbn='979-11-92455-87-7', author='박한희')


class SalesTest(Books):
    def setUp(self):
        super().setUp()
        make_sale(date(2026, 9, 2), 10, book=self.bap, yes24=6, kyobo=4)
        make_sale(date(2026, 9, 23), 26, book=self.bap, yes24=22, kyobo=1, aladin=2, ypbooks=1)
        make_sale(date(2026, 9, 9), 5, book=self.rainbow, kyobo=5)
        make_sale(date(2026, 9, 30), 3, isbn='9791192455999', title='다른 책', local=3)
        make_sale(date(2026, 10, 1), 7, book=self.bap)   # 다음 달은 빼야 한다

    def test_sales_summary(self):
        got = monthly.sales(SEP, SEP_END, FakeBnkClient(readers=READERS, totals=TOTALS))
        self.assertEqual((got['total'], got['kinds']), (44, 3))
        self.assertEqual(got['stores'], {'교보': 10, '예스24': 28, '알라딘': 2, '영풍': 1, '지역서점': 3})
        self.assertEqual(got['weeks'], [('1~7일', 10), ('8~14일', 5), ('15~21일', 0), ('22~28일', 26), ('29~30일', 3)])
        self.assertEqual([(t, n) for t, n, _ in got['top']], [('밥은 먹고 다니냐는 말', 36), ('무지개를 변호하다', 5),
                                                            ('다른 책', 3)])
        self.assertEqual(got['top'][0][2], {'교보': 5, '예스24': 28, '알라딘': 2, '영풍': 1, '지역서점': 0})
        self.assertEqual((got['channels'], got['readers']), ({'pc': 20, 'mobile': 17, 'offline': 7}, READERS))

    def test_last_year_same_month_only_when_that_month_was_fully_read(self):
        make_sale(date(2025, 9, 10), 12, book=self.bap)
        make_sale(date(2025, 10, 1), 9, book=self.bap)   # 다음 달은 빼야 한다
        self.assertIsNone(monthly.sales(SEP, SEP_END, None)['last_year'])
        for i in range(30):
            BnkDay.objects.create(day=date(2025, 9, 1) + timedelta(days=i), read_on=date(2026, 10, 4))
        self.assertEqual(monthly.sales(SEP, SEP_END, None)['last_year'], {'label': '작년 9월', 'total': 12})

    def test_site_lookups_that_fail_leave_those_lines_out(self):
        with self.assertLogs('intake', 'WARNING'):
            got = monthly.sales(SEP, SEP_END, FakeBnkClient(readers=RuntimeError('x'), totals=RuntimeError('x')))
        self.assertEqual((got['total'], got['channels'], got['readers']), (44, None, None))


class EventsTest(Books):
    def test_candidates_of_each_kind_in_date_order_with_sources(self):
        signal(Signal.MOMENT, '인저리타임에 실린 『내란 앞에서』 서평', detail={'summary': '서평이 실려 방에 공유됨'},
               found=at(9, 22))
        signal(Signal.MOMENT, '다음 달 북토크', happens_on=date(2026, 10, 7), detail={'summary': '10월 북토크'})
        signal(Signal.SOCIAL, 'sns1', detail={'posted_on': '2026-09-08', 'summary': '박한희 변호사 대구 북토크 안내',
                                              'who': ['대표'], 'platforms': ['facebook']})
        signal(Signal.SOCIAL, 'sns-sensitive', sensitive=True, detail={'posted_on': '2026-09-09', 'summary': '부고'})
        signal(Signal.NEWS, '수원시민 인권 아카데미 연다', book=self.rainbow, happens_on=date(2026, 9, 23),
               detail={'source': '연합뉴스', 'summary': '박한희 변호사 강연'})
        signal(Signal.NEWS, '관련 없는 기사', relevant=False, happens_on=date(2026, 9, 5))
        signal(Signal.SELECTION, '2026년 세종도서 교양부문', book=self.bap, happens_on=date(2026, 9, 20))
        signal(Signal.REVIEW, 'r1', book=self.rainbow)
        signal(Signal.REVIEW, 'r2', book=self.rainbow)
        camp = FundingCampaign.objects.create(platform='aladin', external_id='3013', url='u', publisher='한티재',
                                              title='농부, 짠한 형 - 두물머리 농사꾼의 농업 비평', is_ours=True,
                                              starts_at=at(9, 18), ends_at=datetime(2026, 10, 12, 0, 0, tzinfo=KST))
        FundingSnapshot.objects.create(campaign=camp, date=date(2026, 9, 30), amount=6966000, goal=5000000, books=387)
        make_call(state=GrantCall.APPLYING, sent_at=at(9, 30), decided_by='운영진A')
        make_book(title='새 책', subtitle='', published=date(2026, 9, 15), isbn='979-11-92455-99-0', author='')
        item = ReviewItem.objects.create(batch='b', title='절판', book=self.bap, options=[], status=ReviewItem.APPLIED,
                                         changed=[['사이트', '판매 상태', True, False]])
        ReviewItem.objects.filter(pk=item.pk).update(updated_at=at(9, 30, 11))
        items = monthly.events(SEP, SEP_END)
        self.assertEqual([(i.no, i.day, i.source) for i in items], [
            (1, date(2026, 9, 8), '대표님 개인 페이스북'),
            (2, date(2026, 9, 15), '사이트 도서 정보'),
            (3, date(2026, 9, 18), '알라딘 북펀드 페이지'),
            (4, date(2026, 9, 20), '공공 선정 발표'),
            (5, date(2026, 9, 22), '검수 방'),
            (6, date(2026, 9, 23), '뉴스 검색'),
            (7, date(2026, 9, 30), '출판진흥원 공고'),
            (8, date(2026, 9, 30), '검수 방 확인'),
            (9, None, '블로그·카페 검색')])
        texts = [i.text for i in items]
        self.assertEqual(texts[2], '『농부, 짠한 형』 북펀드 시작 — 목표의 139%, 387권, 10월 11일 마감')
        self.assertEqual(texts[5], '『무지개를 변호하다』 관련 뉴스 〈연합뉴스〉 「수원시민 인권 아카데미 연다」 — 박한희 변호사 강연')
        self.assertEqual(texts[6], '2026년 제3차 전자책 제작 지원 사업 공고 알림 — 신청하기로 함')
        self.assertEqual(texts[7], '『밥은 먹고 다니냐는 말』 종이책 절판 처리')
        self.assertEqual(texts[8], '새 독자 서평 2건 (『무지개를 변호하다』 2)')

    def test_aladin_funding_without_a_start_is_dated_by_its_latest_snapshot(self):
        camp = FundingCampaign.objects.create(platform='aladin', external_id='3013', url='u', publisher='한티재',
                                              title='농부, 짠한 형 - 부제', is_ours=True,
                                              ends_at=datetime(2026, 10, 12, 0, 0, tzinfo=KST))
        FundingSnapshot.objects.create(campaign=camp, date=date(2026, 9, 27), amount=1, goal=5000000, books=100)
        FundingSnapshot.objects.create(campaign=camp, date=date(2026, 9, 30), amount=6966000, goal=5000000, books=387)
        FundingCampaign.objects.create(platform='aladin', external_id='9', url='u2', publisher='한티재', title='마감 모름',
                                       is_ours=True, starts_at=at(9, 20))
        FundingCampaign.objects.create(platform='tumblbug', external_id='t', url='u3', publisher='한티재', title='텀블벅 책',
                                       is_ours=True, starts_at=at(9, 25), ends_at=datetime(2026, 10, 21, 0, 0, tzinfo=KST))
        found = [(i.day, i.text, i.source) for i in monthly.events(SEP, SEP_END)]
        self.assertEqual(found, [
            (date(2026, 9, 20), '『마감 모름』 북펀드 시작', '알라딘 북펀드 페이지'),
            (date(2026, 9, 25), '『텀블벅 책』 텀블벅 펀딩 시작 — 10월 20일 마감', '텀블벅 페이지'),
            (date(2026, 9, 30), '『농부, 짠한 형』 북펀드 진행 — 목표의 139%, 387권, 10월 11일 마감', '알라딘 북펀드 페이지')])

    def test_one_failing_source_does_not_take_the_others_down(self):
        make_book(title='새 책', subtitle='', published=date(2026, 9, 15), isbn='979-11-92455-99-0', author='')
        signal(Signal.SELECTION, '2026년 세종도서 교양부문', book=self.bap, happens_on=date(2026, 9, 20))
        with mock.patch('marketing.monthly._new_books', side_effect=RuntimeError('db')), \
                self.assertLogs('intake', 'WARNING'):
            found = monthly.events(SEP, SEP_END)
        self.assertEqual([(i.no, i.source) for i in found], [(1, '공공 선정 발표')])


class PostsTest(TestCase):
    def test_counts_this_month_and_unknown_channels(self):
        meta = {'facebook': [OfficialPost('facebook', at(9, 7), '"우리는 혐오가 아니라 우정이 필요해" 박한희 변호사', 'u1'),
                             OfficialPost('facebook', at(10, 1), '다음 달 글', 'u2')],
                'instagram': None}
        blog = [BlogPost('8월 글', 'b1', date(2026, 8, 20), '')]
        book = make_book()
        p = Proposal.objects.create(kind=Proposal.NOW, book=book, headline='『그리운 바람이 나를 불러』 ― 영상이 퍼지는 중')
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='b', status=Draft.POSTED, posted_at=at(9, 30))
        got = monthly.posts(SEP, SEP_END, fetch_meta=lambda since: meta, fetch_blog=lambda: blog)
        self.assertEqual((got['facebook'], got['instagram'], got['blog']), (1, None, 0))
        self.assertEqual(got['samples'], ['페이스북: "우리는 혐오가 아니라 우정이 필요해" 박한희 변호사'])
        self.assertEqual(got['posted'], ['『그리운 바람이 나를 불러』 ― 영상이 퍼지는 중'])
        self.assertIsNone(monthly.posts(SEP, SEP_END, fetch_meta=lambda since: meta, fetch_blog=lambda: None)['blog'])


class NextMonthTest(Books):
    def test_dates_to_prepare(self):
        hook = HookDate.objects.create(name='세계 식량의 날', month=10, day=16)
        hook.books.add(self.bap)
        HookDate.objects.create(name='대구 10월항쟁', month=10, day=1, memorial=True)
        HookDate.objects.create(name='11월 기념일', month=11, day=3)
        make_call(state=GrantCall.APPLYING)   # 10/12 16시 마감
        FundingCampaign.objects.create(platform='aladin', external_id='3013', url='u', publisher='한티재',
                                       title='농부, 짠한 형 - 두물머리 농사꾼의 농업 비평', is_ours=True,
                                       starts_at=at(9, 18), ends_at=datetime(2026, 10, 12, 0, 0, tzinfo=KST))
        signal(Signal.MOMENT, '김해원 저자 북토크', happens_on=date(2026, 10, 7), detail={'summary': ''})
        self.assertEqual(monthly.next_month(OCT), [
            '10/1 대구 10월항쟁(추모)',
            '10/7 김해원 저자 북토크',
            '10/11 『농부, 짠한 형』 북펀드 마감',
            '10/12 16시 2026년 제3차 전자책 제작 지원 사업 공고 신청 마감 (신청하기로 함)',
            '10/16 세계 식량의 날 『밥은 먹고 다니냐는 말』'])

    def test_funding_without_an_end_date_is_skipped_and_a_failing_part_is_isolated(self):
        FundingCampaign.objects.create(platform='aladin', external_id='9', url='u', publisher='한티재', title='마감 모름',
                                       is_ours=True)
        HookDate.objects.create(name='세계 식량의 날', month=10, day=16)
        self.assertEqual(monthly.next_month(OCT), ['10/16 세계 식량의 날'])
        with mock.patch('marketing.monthly.GrantCall.objects') as calls, self.assertLogs('intake', 'WARNING'):
            calls.filter.side_effect = RuntimeError('db')
            self.assertEqual(monthly.next_month(OCT), ['10/16 세계 식량의 날'])


from marketing.tests.fakes import FakeLLM  # noqa: E402


def items():
    return [monthly.Item(1, date(2026, 9, 8), '박한희 변호사 대구 북토크 안내', '대표님 개인 페이스북'),
            monthly.Item(2, date(2026, 9, 22), '인저리타임에 실린 『내란 앞에서』 서평', '검수 방'),
            monthly.Item(3, date(2026, 9, 23), '『무지개를 변호하다』 관련 뉴스 〈연합뉴스〉 「인권 아카데미」', '뉴스 검색')]


FACTS = {'sales': ['합계 263권, 48종', '『밥은 먹고 다니냐는 말』 91권'], 'posts': ['페이스북: 북토크 안내'],
         'next': ['10/16 세계 식량의 날 『밥은 먹고 다니냐는 말』']}


class ComposeTest(Books):
    def test_sources_come_from_cited_items_and_invented_facts_are_dropped(self):
        llm = FakeLLM({'events': [{'text': '9/8 박한희 변호사 대구 북토크', 'from': [1]},
                                  {'text': '9/22 서평을 300명이 읽음', 'from': [2]},           # 지어낸 숫자
                                  {'text': '9/9 박한희 변호사 북토크', 'from': [1]},            # 근거와 다른 날짜
                                  {'text': '없는 근거', 'from': [99]},                          # 없는 번호
                                  {'text': '9/22·9/23 『내란 앞에서』 서평과 박한희 변호사 강연 소식', 'from': [2, 3]}],
                       'posts_topics': '북토크 안내', 'proposals': [
                           '10/16 세계 식량의 날에 『밥은 먹고 다니냐는 말』을 다시 소개해요.',
                           '『없는 책』을 소개해요.', '독자 1000명에게 편지를 보내요.']})
        events, topics, proposals = monthly.compose(llm, '9월', items(), FACTS)
        self.assertEqual(events, [('9/8 박한희 변호사 대구 북토크', '대표님 개인 페이스북'),
                                  ('9/22·9/23 『내란 앞에서』 서평과 박한희 변호사 강연 소식', '검수 방·뉴스 검색')])
        self.assertEqual((topics, proposals), ('북토크 안내', ['10/16 세계 식량의 날에 『밥은 먹고 다니냐는 말』을 다시 소개해요.']))
        self.assertIn('1. 9/8 박한희 변호사 대구 북토크 안내', llm.calls[0][1])

    def test_llm_failure_falls_back_to_the_candidates(self):
        with self.assertLogs('intake', 'WARNING'):
            events, topics, proposals = monthly.compose(FakeLLM('JSON이 아닌 답'), '9월', items(), FACTS)
        self.assertEqual(events[0], ('9/8 박한희 변호사 대구 북토크 안내', '대표님 개인 페이스북'))
        self.assertEqual((len(events), topics, proposals), (3, '', []))

    def test_malformed_llm_shapes_fall_back_instead_of_crashing(self):
        good = {'text': '9/8 박한희 변호사 대구 북토크', 'from': [1]}
        for raw in ([1, 2], {'events': 5}, {'events': [{'text': 'x', 'from': [[1]]}]},
                    {'events': [{'text': 'x', 'from': [{'no': 1}]}]}, {'events': [{'text': 'x', 'from': [True]}]},
                    {'events': [good], 'proposals': 3}, {'events': [good], 'posts_topics': ['a']}):
            with self.subTest(raw=raw):
                events, topics, proposals = monthly.compose(FakeLLM(raw), '9월', items(), FACTS)
                self.assertIn(events, ([('9/8 박한희 변호사 대구 북토크', '대표님 개인 페이스북')],
                                       [(monthly._line(i), i.source) for i in items()]))
                self.assertEqual((topics, proposals), ('', []))

    def test_proposals_and_topics_must_be_plain_text(self):
        llm = FakeLLM({'events': [{'text': '9/8 박한희 변호사 대구 북토크', 'from': [1]}], 'posts_topics': {'a': 1},
                       'proposals': [{'text': '『밥은 먹고 다니냐는 말』'}, '『밥은 먹고 다니냐는 말』을 다시 소개해요.']})
        self.assertEqual(monthly.compose(llm, '9월', items(), FACTS)[1:], ('', ['『밥은 먹고 다니냐는 말』을 다시 소개해요.']))
        self.assertEqual(monthly.compose(FakeLLM({'events': [], 'proposals': '10/16 소개'}), '9월', items(), FACTS)[2], [])

    def test_dates_are_checked_as_month_day_pairs_in_both_forms(self):
        its = items() + [monthly.Item(4, None, '『농부, 짠한 형』 북펀드 진행 — 10월 11일 마감', '알라딘 북펀드 페이지')]
        llm = FakeLLM({'events': [{'text': '『농부, 짠한 형』 북펀드 10/11 마감', 'from': [4]},    # 근거의 '10월 11일'
                                  {'text': '9월 18일 박한희 변호사 대구 북토크', 'from': [1]}],    # 근거는 9/8
                       'proposals': ['10월 16일 세계 식량의 날에 『밥은 먹고 다니냐는 말』을 소개해요.',
                                     '10/1 『밥은 먹고 다니냐는 말』을 소개해요.']})              # '10/16'의 앞부분일 뿐
        events, _, proposals = monthly.compose(llm, '9월', its, FACTS)
        self.assertEqual(events, [('『농부, 짠한 형』 북펀드 10/11 마감', '알라딘 북펀드 페이지')])
        self.assertEqual(proposals, ['10월 16일 세계 식량의 날에 『밥은 먹고 다니냐는 말』을 소개해요.'])


SALES = {'total': 44, 'kinds': 3, 'stores': {'교보': 10, '예스24': 28, '알라딘': 2, '영풍': 1, '지역서점': 3},
         'weeks': [('1~7일', 10), ('8~14일', 5), ('15~21일', 0), ('22~28일', 26), ('29~30일', 3)],
         'top': [('밥은 먹고 다니냐는 말', 36, {'교보': 5, '예스24': 28, '알라딘': 2, '영풍': 1, '지역서점': 0}),
                 ('<지역> 책', 5, {'교보': 5, '예스24': 0, '알라딘': 0, '영풍': 0, '지역서점': 0})],
         'channels': {'pc': 20, 'mobile': 17, 'offline': 7}, 'readers': READERS}
POSTS = {'facebook': 7, 'instagram': None, 'blog': 0, 'samples': [], 'posted': ['『그리운 바람이 나를 불러』 ― 영상']}


class RenderTest(TestCase):
    def test_sections_fold_rule_and_escaping(self):
        text = monthly.render(SEP, SALES, [('9/8 박한희 변호사 대구 북토크', '대표님 개인 페이스북')], '북토크 안내',
                              ['10/16에 『밥은 먹고 다니냐는 말』을 다시 소개해요.'], POSTS, ['10/16 세계 식량의 날'])
        self.assertTrue(text.startswith('<b>📅 9월 돌아보기</b> (9월 1일~30일)\n\n<b>📈 판매 44권 · 3종</b>\n'
                                        '· 교보 10 · 예스24 28 · 알라딘 2 · 영풍 1 · 지역서점 3\n'
                                        '· 온라인 37권(PC 20 · 모바일 17), 서점 매장 7권\n'
                                        '· 7일씩 10 → 5 → 0 → 26 → 3권(마지막은 29~30일)\n'
                                        '· 1위 <b>『밥은 먹고 다니냐는 말』 36권</b>(예스24 28 · 교보 5) — 한 달 판매의 82%\n'
                                        '· 다음: 『&lt;지역&gt; 책』 5\n<blockquote expandable>출처: '))
        self.assertIn('\n\n<b>👥 누가 샀나</b> (구매자 정보가 있는 온라인 판매 190부)\n· 50대 35% · 40대 16% · 60대 이상 16% · 30대 15%\n'
                      '· 여성 61% · 남성 37%\n· 경기 73부 · 서울 32부 · 충북 14부 · 대구 8부\n<blockquote expandable>', text)
        self.assertIn('\n\n<b>🗂 9월에 있었던 일</b> (1가지 · 눌러서 보기)\n<blockquote expandable>· 9/8 박한희 변호사 대구 북토크 '
                      '(대표님 개인 페이스북)</blockquote>', text)
        self.assertIn('\n\n<b>📣 우리가 올린 글</b>\n· 페이스북 페이지 7편 · 인스타그램 확인 못 함 · 네이버 블로그 0편\n· 북토크 안내\n'
                      '· 봇 제안 중 올린 글: 『그리운 바람이 나를 불러』 ― 영상\n<blockquote expandable>', text)
        self.assertIn('\n\n<b>🗓 10월 준비</b>\n· 10/16 세계 식량의 날', text)
        self.assertTrue(text.endswith('\n\n<b>💡 제안</b>\n<b>1.</b> 10/16에 『밥은 먹고 다니냐는 말』을 다시 소개해요.'))

    def test_long_lines_are_clipped_and_events_dropped_to_fit_telegram(self):
        long_events = [(f'9/{d} ' + '아주 긴 소식 😀 ' * 60, '검수 방') for d in range(1, 11)]
        text = monthly.render(SEP, SALES, long_events, '주제 ' * 200, ['제안 ' * 200, '둘째 제안'], POSTS,
                              [f'10/{d} ' + '기념일 ' * 30 for d in range(1, 13)])
        self.assertLessEqual(tg_len(text), TEXT_LIMIT)
        shown = text.split('<blockquote expandable>· ')[1].split('</blockquote>')[0].split('\n')
        self.assertIn(f'({len(shown)}가지 · 눌러서 보기)', text)
        self.assertTrue(all(tg_len(line) <= monthly.LINE_LIMIT + 20 for line in shown))
        self.assertTrue(text.endswith('<b>2.</b> 둘째 제안'))

    def test_last_year_goes_next_to_the_total_and_into_the_facts(self):
        s = {**SALES, 'last_year': {'label': '작년 9월', 'total': 52}}
        self.assertIn('<b>📈 판매 44권 · 3종</b> · 작년 9월 52권\n', monthly.render(SEP, s, [], '', [], POSTS, []))
        self.assertIn('작년 9월 합계 52권', monthly._sales_facts(s))
        self.assertNotIn('작년', monthly.render(SEP, {**SALES, 'last_year': None}, [], '', [], POSTS, []))

    def test_missing_site_lookups_and_empty_sections_are_left_out(self):
        bare = {**SALES, 'channels': None, 'readers': None}
        text = monthly.render(SEP, bare, [], '', [], {**POSTS, 'posted': []}, [])
        for absent in ('온라인 37권', '👥', '🗂', '🗓', '💡'):
            self.assertNotIn(absent, text)


class BuildTest(TestCase):
    def test_nothing_until_the_month_is_fully_read(self):
        c = FakeBnkClient(readers=READERS, totals=TOTALS)
        self.assertEqual(monthly.build(FakeLLM({}), c, SEP, at(10, 3), fetch_meta=lambda s: {}, fetch_blog=lambda: []), '')
        self.assertEqual(c.asked, [])


    def test_an_ads_error_leaves_out_only_the_ads_section(self):
        with mock.patch('marketing.monthly.bnk_sales.month_ready', return_value=True), \
                mock.patch('marketing.monthly.ads.month_items', side_effect=RuntimeError('boom')), \
                self.assertLogs('intake', 'WARNING') as logs:
            text = monthly.build(FakeLLM({}), None, SEP, at(10, 3), fetch_meta=lambda s: {}, fetch_blog=lambda: [])
        self.assertTrue(text.startswith('<b>📅 9월 돌아보기</b>'))
        self.assertNotIn('💸', text)
        self.assertTrue(any('monthly: ads failed' in line for line in logs.output))


class AdsSectionTest(TestCase):
    def test_ads_section_follows_posts_and_is_absent_without_ads(self):
        lines = ['광고 1건 · 광고비 35,000원', '『산속』 글: 7일 · 35,000원 · 지금까지 7,000명에게 보였어요']
        text = monthly.render(SEP, SALES, [], '', [], POSTS, [], ads_lines=lines)
        self.assertIn('<b>💸 광고 1건 · 광고비 35,000원</b>\n· 『산속』 글: 7일', text)
        self.assertLess(text.index('📣'), text.index('💸'))
        self.assertIn(monthly.h(monthly.ADS_SOURCE), text)
        self.assertNotIn('💸', monthly.render(SEP, SALES, [], '', [], POSTS, []))

    def test_ad_numbers_may_appear_in_proposals(self):
        from marketing.monthly import _check
        raw = {'events': [], 'posts_topics': '', 'proposals': ['광고비 35,000원을 쓴 글처럼 북펀드 소식을 다시 올려 보세요']}
        _, _, proposals = _check(raw, [], {'ads': ['광고 1건 · 광고비 35,000원']})
        self.assertEqual(len(proposals), 1)

    def test_user_message_lists_ads_only_when_there_are_some(self):
        from marketing.prompts import build_monthly_user
        self.assertIn('[광고]\n광고 1건', build_monthly_user('9월', [], {'ads': ['광고 1건 · 광고비 35,000원']}))
        self.assertNotIn('[광고]', build_monthly_user('9월', [], {}))
