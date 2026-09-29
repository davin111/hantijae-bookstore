from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import TestCase

from intake.models import FundingCampaign
from marketing import candidates as C
from marketing.briefing import build_weekly
from marketing.meta import OfficialPost
from marketing.models import Signal
from marketing.tests.fakes import FakeLLM, make_book
from marketing.timeutil import KST

TODAY = date(2026, 9, 28)
NOW = datetime(2026, 9, 28, 7, 0, tzinfo=KST)


def unknown(since):
    return {'facebook': None, 'instagram': None}


def boom(since):
    raise AssertionError('Meta를 부르면 안 됨')


def sns(key, category='event', books=(), titles=(), event=None, summary='요약', posted_on='2026-09-25', **kw):
    ev = event or {}
    return Signal.objects.create(
        kind=Signal.SOCIAL, key=f'social:{key}', title='t', relevant=True, url=f'https://example.com/{key}',
        book=books[0] if books else None,
        happens_on=date.fromisoformat(ev['on']) if ev.get('on') else date.fromisoformat(posted_on),
        detail={'category': category, 'summary': summary, 'event': event, 'books': [b.id for b in books],
                'titles': list(titles), 'who': ['대표'], 'platforms': ['facebook'], 'posted_on': posted_on,
                'link': {'source': '한겨레'} if category == 'press' else {}}, **kw)


def pick(cid):
    return {'items': [{'candidate_id': cid, 'headline': '서평 모음 ― 이번 주', 'reason': '이유',
                       'draft': {'channel': 'blog', 'title': '', 'body': '글'}}]}


class SocialCandidateTest(TestCase):
    def setUp(self):
        self.rainbow = make_book(title='무지개를 변호하다', published=date(2026, 6, 1), isbn='979-11-00000-14-1', author=None)
        self.farmer = make_book(title='농부, 짠한 형', published=date(2026, 9, 10), isbn='979-11-00000-15-1', author=None)

    def test_upcoming_event_candidate_with_official_note(self):
        s = sns('e1', books=[self.rainbow], event={'on': '2026-10-03', 'name': '북토크', 'place': '대구'})
        blog = [SimpleNamespace(title='다른 글', date=date(2026, 9, 26))]
        [c] = C.social_candidates(TODAY, NOW, blog, fetch=lambda since: {'facebook': [], 'instagram': None})
        self.assertEqual((c.id, c.kind, c.urgency, c.books, c.signal), (f'sns:{s.id}', 'sns_event', 3, [self.rainbow], s))
        self.assertEqual(c.summary, '10월 3일 북토크(대구) ― 대표님 개인 페이스북에 안내가 있음, '
                                    '공식 블로그·페이스북 페이지엔 아직 없음, 확인 못 한 곳: 인스타')
        self.assertEqual(c.facts['official'], {'블로그': '없음', '인스타': '모름', '페이스북 페이지': '없음'})
        self.assertEqual(C.KIND_LABEL['sns_event'], '다가오는 행사')

    def test_unknown_official_channel_is_not_called_missing(self):
        sns('n1', category='new_book', books=[self.farmer], summary='『농부, 짠한 형』 출간')
        [c] = C.social_candidates(TODAY, NOW, None, fetch=unknown)
        self.assertEqual(c.kind, 'sns_repost')
        self.assertIn('확인 못 한 곳: 블로그·인스타·페이스북 페이지', c.summary)
        self.assertNotIn('없음', c.summary)

    def test_event_after_and_far_future(self):
        after = sns('a', event={'on': '2026-09-22', 'name': '낭독회', 'place': ''})
        sns('far', event={'on': '2026-11-30', 'name': '강연', 'place': ''})
        sns('old', event={'on': '2026-09-10', 'name': '옛 행사', 'place': ''})
        [c] = C.social_candidates(TODAY, NOW, [], fetch=unknown)
        self.assertEqual((c.id, c.kind, c.urgency), (f'sns:{after.id}', 'sns_after', 1))
        self.assertEqual(c.summary, '지난 9월 22일 낭독회 ― 후기를 공식 채널에 올릴 수 있음')

    def test_repost_skipped_when_every_official_channel_has_it(self):
        sns('n1', category='new_book', books=[self.farmer])
        blog = [SimpleNamespace(title='『농부, 짠한 형』 ― 새 책', date=date(2026, 9, 24))]
        when = datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc)
        meta = {'facebook': [OfficialPost('facebook', when, '새 책 농부, 짠한 형', 'u')],
                'instagram': [OfficialPost('instagram', when, '#농부짠한형 새 책 『농부, 짠한 형』', 'u')]}
        self.assertEqual(C.social_candidates(TODAY, NOW, blog, fetch=lambda since: meta), [])

    def test_bookless_sns_candidate_passes_select(self):
        s = sns('n1', category='new_book', titles=['바람의 책'], summary='신간 『바람의 책』 예고')
        cands = C.gather(TODAY, NOW, posts=[])
        [c] = [c for c in cands if c.signal == s]
        self.assertEqual((c.books, c.facts['not_on_site']), ([], ['바람의 책']))

    def test_press_signals_become_one_candidate(self):
        a = sns('p1', category='press', books=[self.rainbow], summary='저자 인터뷰')
        b = sns('p2', category='review', books=[self.farmer], summary='독자 서평')
        [c] = C.social_candidates(TODAY, NOW, [], fetch=boom)  # 최근 것부터(같은 날이면 나중에 찾은 것부터)
        self.assertEqual((c.id, c.kind, c.signal, c.more_signals), ('sns_press:2026-09-28', 'sns_press', b, [a]))
        self.assertEqual(c.books, [self.farmer, self.rainbow])
        self.assertEqual(c.summary, '운영진이 최근 공유한 서평·기사 ― 독자 서평 / 저자 인터뷰')

    def test_funding_post_merges_into_fund_candidate(self):
        FundingCampaign.objects.create(platform='aladin', external_id='3013', url='u', title='농부, 짠한 형',
                                       publisher='한티재', starts_at=NOW - timedelta(days=10),
                                       ends_at=datetime(2026, 10, 12, 0, 0, tzinfo=KST), is_ours=True)
        s = sns('f1', category='funding', books=[self.farmer])
        cands = C.gather(TODAY, NOW, posts=[])
        self.assertFalse(any(c.signal == s for c in cands))
        fund = next(c for c in cands if c.kind == 'fund')
        self.assertEqual(fund.facts['personal_posts'], ['2026-09-25 대표님 개인 페이스북'])

    def test_no_social_signal_no_meta_call(self):
        self.assertEqual(C.social_candidates(TODAY, NOW, [], fetch=boom), [])

    def test_rebuilding_same_week_keeps_press_item_and_marks_all(self):
        a = sns('p1', category='press', summary='저자 인터뷰')
        b = sns('p2', category='review', summary='독자 서평')
        llm = FakeLLM(pick('sns_press:2026-09-28'))
        keys = []
        for _ in range(3):
            brief, _ = build_weekly(llm, TODAY, NOW, posts=[])
            keys.append(list(brief.items.values_list('candidate_key', flat=True)))
        self.assertEqual(keys, [['sns_press:2026-09-28']] * 3)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertIsNotNone(a.used_at)
        self.assertIsNotNone(b.used_at)
        self.assertEqual(brief.items.get().extra, {'signals': [a.id]})

    def test_context_lines_reach_prompt(self):
        sns('n1', category='new_book', books=[self.farmer], summary='『농부, 짠한 형』 출간')
        llm = FakeLLM({'items': []})
        build_weekly(llm, TODAY, NOW, posts=[])
        user = llm.calls[0][1]
        self.assertIn('<참고: 운영진이 최근 개인 SNS에 올린 한티재 소식(후보 아님)>', user)
        self.assertIn('2026-09-25 대표님 개인 페이스북: 『농부, 짠한 형』 출간', user)

    def test_dated_event_wins_over_press_category(self):
        s = sns('q1', category='author_news', event={'on': '2026-10-02', 'name': '저자 모임 부스', 'place': ''})
        [c] = C.social_candidates(TODAY, NOW, [], fetch=unknown)
        self.assertEqual((c.kind, c.signal), ('sns_event', s))

    def test_official_lookback_and_shared_official_page(self):
        s = sns('f2', category='funding', titles=['바람의 책'], posted_on='2026-09-25')
        s.detail = {**s.detail, 'shared_urls': ['https://www.facebook.com/hantijae/posts/pfbidX']}
        s.save()
        old_ig = [OfficialPost('instagram', datetime(2026, 9, 18, 1, 0, tzinfo=timezone.utc), '『바람의 책』 펀딩', 'u')]
        status = C.official_status(s, None, {'instagram': old_ig, 'facebook': []})
        self.assertEqual(status, {'blog': None, 'instagram': True, 'facebook': True})

    def test_event_is_on_official_only_when_the_day_is_mentioned(self):
        s = sns('e2', books=[self.rainbow], event={'on': '2026-10-03', 'name': '북토크', 'place': ''})
        when = datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc)
        other_day = {'instagram': [OfficialPost('instagram', when, '『무지개를 변호하다』 새 리뷰', 'u')], 'facebook': None}
        that_day = {'instagram': [OfficialPost('instagram', when, '10월 3일 『무지개를 변호하다』 북토크', 'u')], 'facebook': None}
        self.assertFalse(C.official_status(s, None, other_day)['instagram'])
        self.assertTrue(C.official_status(s, None, that_day)['instagram'])

    def test_untitled_funding_post_joins_the_only_live_fund(self):
        FundingCampaign.objects.create(platform='aladin', external_id='3013', url='u', title='농부, 짠한 형',
                                       publisher='한티재', starts_at=NOW - timedelta(days=10),
                                       ends_at=datetime(2026, 10, 12, 0, 0, tzinfo=KST), is_ours=True)
        s = sns('f3', category='funding', summary='펀딩 참여 부탁')
        cands = C.gather(TODAY, NOW, posts=[])
        self.assertFalse(any(c.signal == s for c in cands))
        self.assertEqual(next(c for c in cands if c.kind == 'fund').facts['personal_posts'], ['2026-09-25 대표님 개인 페이스북'])
