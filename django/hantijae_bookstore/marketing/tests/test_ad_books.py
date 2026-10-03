import json
from datetime import date, datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from intake.models import FundingCampaign
from marketing import ad_books, ads
from marketing.models import Ad, Draft, Proposal
from marketing.tests.fakes import FakeLLM, make_ad, make_book
from marketing.timeutil import KST

NONGBU = '한티재에서 준비하고 있는 다음 책은 <농부, 짠한 형>입니다. 알라딘 북펀드 중이에요.'
NONGBU_NO_TITLE = '“재미없을수록 재밌게 살자!” 두물머리 20년차 유기농 농부의 능청스런 수다'


def funding(title, ours=True, external_id='1'):
    return FundingCampaign.objects.create(platform=FundingCampaign.ALADIN, external_id=external_id,
                                          url=f'https://f/{external_id}', title=title, is_ours=ours)


class Broken:
    """AI 연결이 실패하는 흉내."""

    def __init__(self, error=None):
        self.calls, self.error = 0, error or RuntimeError('sidecar down')

    def complete(self, system, user, attachments=()):
        self.calls += 1
        raise self.error


def pick(title):
    """AI가 후보 목록에서 그 제목을 고른 답(번호는 지금 후보 순서대로)."""
    number = next(i for i, c in enumerate(ad_books.candidates(), 1) if c.title == title)
    return {'book': number, 'title': title}


class FundingTitleTest(TestCase):
    def test_book_title_comes_from_brackets_or_before_the_subtitle(self):
        self.assertEqual(ad_books.funding_book_title('농부, 짠한 형 - 두물머리 농사꾼의 농업 비평'), '농부, 짠한 형')
        self.assertEqual(ad_books.funding_book_title('<프루동 평전> 국내 최초 번역 출판'), '프루동 평전')
        self.assertEqual(ad_books.funding_book_title('성서는 정말 동성애를 금지할까? <성서, 퀴어를 옹호하다>'),
                         '성서, 퀴어를 옹호하다')
        self.assertEqual(ad_books.funding_book_title('농부, 짠한 형 — 두물머리 농사꾼의 농업 비평'), '농부, 짠한 형')
        self.assertEqual(ad_books.funding_book_title('농부, 짠한 형: 두물머리 농사꾼의 농업 비평'), '농부, 짠한 형')

    def test_funding_title_overlapping_a_site_title_is_not_a_second_candidate(self):
        make_book(title='기후정의', isbn='979-11-00000-05-5')
        funding('기후정의 개정판 펀딩 안내', external_id='1')
        self.assertEqual([c.title for c in ad_books.candidates() if c.book is None], [])

    def test_candidates_add_our_funding_books_missing_from_the_site(self):
        make_book(title='프루동 평전', isbn='979-11-00000-02-2')
        funding('농부, 짠한 형 - 두물머리 농사꾼의 농업 비평', external_id='1')
        funding('<프루동 평전> 국내 최초 번역 출판', external_id='2')   # 사이트에 이미 있다
        funding('다른 출판사 책 - 부제', ours=False, external_id='3')
        extra = [c for c in ad_books.candidates() if c.book is None]
        self.assertEqual([(c.title, c.about) for c in extra],
                         [('농부, 짠한 형', '농부, 짠한 형 - 두물머리 농사꾼의 농업 비평 (북펀드)')])


class MatchTest(TestCase):
    def test_bot_placement_wins(self):
        book = make_book(title='농부의 나라', isbn='979-11-00000-03-3')
        p = Proposal.objects.create(kind=Proposal.NOW, book=book, headline='x')
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='b', status=Draft.POSTED,
                             placements=[{'kind': 'facebook', 'id': '111_7', 'label': 'x', 'url': 'u', 'at': ''}])
        self.assertEqual(ad_books.match(('111_7', ''), '아무 글'), (book, ''))

    def test_site_book_by_title(self):
        book = make_book()
        self.assertEqual(ad_books.match(('111_1',), '『나는 산속으로 더 깊이 들어간다』 2쇄'), (book, ''))

    def test_funding_book_not_on_the_site_gives_its_title(self):
        funding('농부, 짠한 형 - 두물머리 농사꾼의 농업 비평')
        self.assertEqual(ad_books.match(('111_1',), NONGBU), (None, '농부, 짠한 형'))

    def test_two_site_books_with_the_same_title_give_nothing(self):
        make_book(title='같은 제목', isbn='979-11-00000-06-6')
        make_book(title='같은 제목', isbn='979-11-00000-07-7')
        self.assertEqual(ad_books.match((), '『같은 제목』 개정판'), (None, ''))

    def test_two_titles_or_none_give_nothing(self):
        make_book()
        funding('농부, 짠한 형 - 두물머리 농사꾼의 농업 비평')
        self.assertEqual(ad_books.match((), NONGBU + ' 『나는 산속으로 더 깊이 들어간다』'), (None, ''))
        self.assertEqual(ad_books.match((), '서점의 날 행사 안내'), (None, ''))


class RelinkTest(TestCase):
    def test_site_book_registered_later_links_the_ad_and_clears_the_funding_title(self):
        funding('농부, 짠한 형 - 두물머리 농사꾼의 농업 비평')
        ad = make_ad(post_text=NONGBU, book_title='농부, 짠한 형', days=[date(2026, 9, 22)])
        self.assertEqual(ad_books.relink().linked, 0)   # 그대로
        book = make_book(title='농부, 짠한 형', isbn='979-11-00000-04-4')
        result = ad_books.relink()
        ad.refresh_from_db()
        self.assertEqual((result.linked, ad.book, ad.book_title), (1, book, ''))

    def test_funding_title_is_found_for_an_old_ad(self):
        funding('농부, 짠한 형 - 두물머리 농사꾼의 농업 비평')
        ad = make_ad(post_text=NONGBU, days=[date(2026, 9, 22)])
        ad_books.relink()
        ad.refresh_from_db()
        self.assertEqual((ad.book, ad.book_title), (None, '농부, 짠한 형'))
        self.assertEqual(ads.name(ad), '『농부, 짠한 형』 글')

    def test_ai_picks_a_book_when_the_title_is_not_written_and_is_asked_once(self):
        funding('농부, 짠한 형 - 두물머리 농사꾼의 농업 비평')
        make_book()
        ad = make_ad(post_text=NONGBU_NO_TITLE, days=[date(2026, 9, 22)])
        answer = pick('농부, 짠한 형')
        llm = FakeLLM(answer)
        result = ad_books.relink(llm)
        ad.refresh_from_db()
        self.assertEqual((result.asked, result.linked, ad.book_title), (1, 1, '농부, 짠한 형'))
        self.assertIsNotNone(ad.book_asked_at)
        system, user = llm.calls[0]
        self.assertIn('[광고 글]\n' + NONGBU_NO_TITLE, user)
        self.assertIn(f"{answer['book']}. 농부, 짠한 형 — 농부, 짠한 형 - 두물머리 농사꾼의 농업 비평 (북펀드)", user)
        ad_books.relink(llm)
        self.assertEqual(len(llm.calls), 1)   # 광고마다 한 번만

    def test_title_chosen_by_ai_turns_into_the_site_book_once_it_is_registered(self):
        funding('농부, 짠한 형 - 두물머리 농사꾼의 농업 비평')
        ad = make_ad(post_text=NONGBU_NO_TITLE, days=[date(2026, 9, 22)])
        ad_books.relink(FakeLLM(pick('농부, 짠한 형')))
        book = make_book(title='농부, 짠한 형', isbn='979-11-00000-04-4')
        llm = FakeLLM({'book': None})
        result = ad_books.relink(llm)
        ad.refresh_from_db()
        self.assertEqual((result.linked, ad.book, ad.book_title, len(llm.calls)), (1, book, '', 0))

    def test_an_ad_with_a_title_already_is_not_asked(self):
        ad = make_ad(post_text='제목 없는 글', book_title='농부, 짠한 형', days=[date(2026, 9, 22)])
        llm = FakeLLM({'book': None})
        ad_books.relink(llm)
        ad.refresh_from_db()
        self.assertEqual((len(llm.calls), ad.book_title), (0, '농부, 짠한 형'))

    def test_a_number_whose_title_does_not_match_is_corrected_or_dropped(self):
        make_book()
        make_book(title='우리 힘세고 사나운 용기', isbn='979-11-00000-08-8')
        right = make_ad(ad_id='1', post_id='111_1', post_text='산 시집 소식', days=[date(2026, 9, 22)])
        wrong = make_ad(ad_id='2', post_id='111_2', post_text='무슨 글', days=[date(2026, 9, 22)])
        sansok = pick('나는 산속으로 더 깊이 들어간다')
        off_by_one = {'book': sansok['book'] % 2 + 1, 'title': '나는 산속으로 더 깊이 들어간다'}   # 번호만 어긋남
        nonsense = {'book': 1, 'title': '없는 책'}
        ad_books.relink(FakeLLM([off_by_one, nonsense]))
        right.refresh_from_db()
        wrong.refresh_from_db()
        self.assertEqual(right.book.title, '나는 산속으로 더 깊이 들어간다')
        self.assertEqual((wrong.book, wrong.book_title), (None, ''))

    def test_asks_at_most_five_a_run(self):
        make_book()
        for i in range(7):
            make_ad(ad_id=str(i), post_id=f'111_{i}', post_text=f'무슨 글 {i}', days=[date(2026, 9, 22)])
        llm = FakeLLM({'book': None})
        self.assertEqual(ad_books.relink(llm).asked, 5)
        self.assertEqual(ad_books.relink(llm).asked, 2)

    def test_first_ai_error_stops_asking_for_this_run(self):
        make_book()
        for i in range(3):
            make_ad(ad_id=str(i), post_id=f'111_{i}', post_text=f'무슨 글 {i}', days=[date(2026, 9, 22)])
        broken = Broken()
        with self.assertLogs('intake', level='WARNING'):
            result = ad_books.relink(broken)
        self.assertEqual((broken.calls, result.failed, result.asked), (1, 1, 1))
        self.assertFalse(Ad.objects.filter(book_asked_at__isnull=False).exists())

    def test_an_answer_that_is_never_json_is_remembered_as_asked(self):
        from intake.llm import LLMInvalidJSON
        make_book()
        ad = make_ad(post_text='무슨 글', days=[date(2026, 9, 22)])
        with self.assertLogs('intake', level='WARNING'):
            ad_books.relink(Broken(LLMInvalidJSON('not json')))
        ad.refresh_from_db()
        self.assertIsNotNone(ad.book_asked_at)

    def test_a_book_chosen_by_the_operator_meanwhile_is_kept(self):
        make_book()
        chosen = make_book(title='우리 힘세고 사나운 용기', isbn='979-11-00000-08-8')
        ad = make_ad(post_text='무슨 글', days=[date(2026, 9, 22)])
        answer = json.dumps(pick('나는 산속으로 더 깊이 들어간다'), ensure_ascii=False)   # AI는 다른 책을 고른다

        class Meanwhile:
            def complete(self, system, user, attachments=()):
                Ad.objects.filter(pk=ad.pk).update(book=chosen)   # 관리자 화면에서 그사이 고름
                return answer

        ad_books.relink(Meanwhile())
        ad.refresh_from_db()
        self.assertEqual(ad.book, chosen)

    def test_ai_can_pick_a_site_book(self):
        book = make_book()
        ad = make_ad(post_text='산속 시집 2쇄 소식', days=[date(2026, 9, 22)])
        ad_books.relink(FakeLLM({'book': 1, 'title': book.title}))
        ad.refresh_from_db()
        self.assertEqual((ad.book, ad.book_title), (book, ''))

    def test_ai_saying_none_or_out_of_range_is_remembered_without_a_book(self):
        make_book()
        event = make_ad(ad_id='1', post_id='111_1', post_text='11월 11일은 서점의 날입니다', days=[date(2026, 9, 22)])
        odd = make_ad(ad_id='2', post_id='111_2', post_text='무슨 글', days=[date(2026, 9, 22)])
        llm = FakeLLM([{'book': None}, {'book': 99}])
        result = ad_books.relink(llm)
        for ad in (event, odd):
            ad.refresh_from_db()
            self.assertEqual((ad.book, ad.book_title), (None, ''))
            self.assertIsNotNone(ad.book_asked_at)
        self.assertEqual((result.asked, result.linked), (2, 0))

    def test_ai_failure_is_retried_next_time(self):
        make_book()
        ad = make_ad(post_text='무슨 글', days=[date(2026, 9, 22)])
        broken = Broken()
        with self.assertLogs('intake', level='WARNING') as cm:
            result = ad_books.relink(broken)
        self.assertEqual((result.failed, broken.calls), (1, 1))
        self.assertNotIn('무슨 글', '\n'.join(cm.output))
        ad.refresh_from_db()
        self.assertIsNone(ad.book_asked_at)
        ad_books.relink(FakeLLM({'book': None}))
        ad.refresh_from_db()
        self.assertIsNotNone(ad.book_asked_at)

    def test_blank_posts_are_skipped_and_without_ai_nobody_is_asked(self):
        make_book()
        blank = make_ad(ad_id='1', post_id='111_1', post_text='', days=[date(2026, 9, 22)])
        text = make_ad(ad_id='2', post_id='111_2', post_text='무슨 글', days=[date(2026, 9, 22)])
        result = ad_books.relink(None)   # AI 없이: 글자 맞추기만
        text.refresh_from_db()
        self.assertEqual((result.asked, text.book, text.book_asked_at), (0, None, None))
        llm = FakeLLM({'book': None})
        ad_books.relink(llm)
        blank.refresh_from_db()
        self.assertEqual((len(llm.calls), blank.book_asked_at), (1, None))   # 글이 빈 광고는 묻지 않는다

    def test_command_relinks_now_and_lists_what_changed(self):
        funding('농부, 짠한 형 - 두물머리 농사꾼의 농업 비평')
        make_ad(post_text=NONGBU, days=[date(2026, 9, 21), date(2026, 9, 30)])
        out = StringIO()
        call_command('marketing_ads_relink', '--no-ai', stdout=out)
        text = out.getvalue()
        self.assertIn('책·제목을 새로 정한 광고 1개', text)
        self.assertIn('『농부, 짠한 형』 글 9월 21일~30일', text)


class CardAndRunTest(TestCase):
    def test_card_says_the_book_is_not_on_the_site_yet(self):
        ad = make_ad(post_text=NONGBU, book_title='농부, 짠한 형', days=[date(2026, 9, 22)], reach=6000)
        text = ads.card_text([ad], datetime(2026, 10, 1, 10, 0, tzinfo=KST), fetch=lambda s, u: {'facebook': []})
        self.assertIn('『농부, 짠한 형』 글', text)
        self.assertIn('아직 사이트 도서 목록에 없는 책이라 판매는 뺐어요', text)
        self.assertNotIn('어느 책 광고인지 몰라', text)

    def test_run_relinks_with_the_given_ai_after_collecting(self):
        with mock.patch('marketing.ads.configured', return_value=True), \
                mock.patch('marketing.ads.collect', return_value=ads.Report(found=1, ours=1)), \
                mock.patch('marketing.ads.remind_expiry'), \
                mock.patch('marketing.ad_books.relink', return_value=ad_books.Relinked(linked=2)) as relink:
            llm = object()
            report = ads.run(date(2026, 10, 3), notify=lambda text: None, llm=llm)
        relink.assert_called_once_with(llm)
        self.assertEqual(report.linked, 2)
        self.assertIn('책을 새로 정한 광고 2개', ads.report_text(report))

    def test_a_relink_failure_does_not_undo_a_successful_collection(self):
        from intake.models import WorkerState
        with mock.patch('marketing.ads.configured', return_value=True), \
                mock.patch('marketing.ads.collect', return_value=ads.Report(found=1, ours=1)), \
                mock.patch('marketing.ads.remind_expiry'), \
                mock.patch('marketing.ad_books.relink', side_effect=RuntimeError('db')):
            with self.assertLogs('intake', level='WARNING') as cm:
                report = ads.run(date(2026, 10, 3), notify=lambda text: None, llm=object())
        self.assertIsNotNone(report)
        self.assertEqual(WorkerState.get('ads_ok_on'), '2026-10-03')
        self.assertIn('ads relink: RuntimeError', '\n'.join(cm.output))

    def test_prompt_asks_for_the_title_too(self):
        from marketing.prompts import AD_BOOK_SYSTEM
        self.assertIn('"title"', AD_BOOK_SYSTEM)
