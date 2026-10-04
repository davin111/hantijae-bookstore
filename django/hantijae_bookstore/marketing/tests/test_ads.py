import json
from datetime import date, datetime, timedelta, timezone as dt_tz
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from django.test import override_settings

from intake.models import WorkerState
from marketing import ads, meta
from marketing.bot import Marketing
from marketing.meta import ChannelPost
from marketing.models import Ad, AdDay, BnkDay, Draft, Proposal
from marketing.tests.fakes import FakeLLM, FakeTG, make_ad, make_book, make_sale
from marketing.tests.test_bot import FakeHost
from marketing.tests.test_meta_reads import FakeGraph, err
from marketing.timeutil import KST


class ModelTest(TestCase):
    def test_make_ad_fills_spend_days_and_first_last_day(self):
        ad = make_ad(book=make_book(), days=[date(2026, 9, 24), date(2026, 9, 22), date(2026, 9, 23)], daily=5000)
        self.assertEqual((ad.first_day, ad.last_day, ad.spend, ad.card), (date(2026, 9, 22), date(2026, 9, 24), 15000,
                                                                         Ad.PENDING))
        self.assertEqual(AdDay.objects.filter(ad=ad).count(), 3)

    def test_one_row_per_ad_and_day(self):
        ad = make_ad(days=[date(2026, 9, 22)])
        with self.assertRaises(IntegrityError), transaction.atomic():
            AdDay.objects.create(ad=ad, day=date(2026, 9, 22))


CFG = {'META_ADS_TOKEN': 'atok', 'META_AD_ACCOUNT_ID': 'act_1', 'META_APP_SECRET': 'sec', 'META_PAGE_TOKEN': 'ptok',
       'META_PAGE_ID': '111', 'META_IG_USER_ID': '222', 'META_ADS_EXPIRES': '2026-11-30'}
TODAY = date(2026, 10, 3)


def day_row(ad_id, day, spend='5000', **extra):
    return {'ad_id': ad_id, 'date_start': day, 'date_stop': day, 'spend': spend, 'impressions': '1000',
            'clicks': '100', 'inline_link_clicks': '7',
            'actions': [{'action_type': 'post_reaction', 'value': '60'}, {'action_type': 'post_engagement', 'value': '120'},
                        {'action_type': 'link_click', 'value': '7'}], **extra}


class Graph(FakeGraph):
    """광고 1: 한티재 페북 글 / 2: 다른 페이지 글 / 3: 인스타 글(주인 222)."""

    def __init__(self, found=('1', '2', '3'), creatives=None, owners=None, days=None, totals=None, broken=(),
                 post_errors=None, post_text=None, unlisted=(), unreadable=()):
        self.unlisted, self.unreadable = set(unlisted), dict.fromkeys(unreadable, 100)   # 목록에서 빠진 광고 / 따로 읽을 때 실패
        self.post_errors = post_errors or {}
        self.post_text = post_text or '『나는 산속으로 더 깊이 들어간다』 2쇄를 찍었습니다'
        self.found = found
        self.creatives = creatives or {'1': {'effective_object_story_id': '111_10', 'effective_instagram_media_id': '900'},
                                       '2': {'effective_object_story_id': '555_20'},
                                       '3': {'effective_instagram_media_id': '901'}}
        self.owners = {'901': '222'} if owners is None else owners
        self.days = days if days is not None else [day_row('1', '2026-09-22', '30000.00'), day_row('3', '2026-09-23')]
        self.totals = totals or {'1': {'spend': '30000', 'impressions': '9000', 'reach': '6000', 'clicks': '1200',
                                       'inline_link_clicks': '50', 'actions': [{'action_type': 'post_reaction',
                                                                                'value': '500'}]}}
        self.broken = set(broken)
        super().__init__(self.answer)

    def answer(self, path, params):
        if path in self.broken:
            return err(1)
        if path == 'act_1/insights':
            return (200, {'data': self.days}) if 'time_increment' in params else \
                (200, {'data': [{'ad_id': i} for i in self.found]})
        if path == 'act_1/ads':
            return 200, {'data': [{'id': i, 'creative': self.creatives[i]}
                                  for i in json.loads(params['filtering'])[0]['value'] if i not in self.unlisted]}
        if path in self.creatives and params.get('fields') == ads.CREATIVE:   # 광고 하나를 따로 읽기
            return err(self.unreadable[path]) if path in self.unreadable else (200, {'creative': self.creatives[path],
                                                                                    'id': path})
        if path.endswith('/insights') and 'time_increment' in params:   # 광고 자체의 일별 줄
            return 200, {'data': [r for r in self.days if r['ad_id'] == path.split('/')[0]]}
        if path.endswith('/insights'):
            return 200, {'data': [self.totals.get(path.split('/')[0], {})]}
        if params.get('fields') == 'owner':
            owner = self.owners.get(path)
            return err(owner) if isinstance(owner, int) else ((200, {'owner': {'id': owner}}) if owner else err(100))
        if path in self.post_errors and params.get('fields', '').split(',')[0] in ('message', 'caption'):
            return err(self.post_errors[path])
        if params.get('fields', '').startswith('message'):
            return 200, {'message': self.post_text, 'permalink_url': 'https://f/10',
                         'created_time': '2026-09-19T01:00:00+0000'}
        if params.get('fields', '').startswith('caption'):
            return 200, {'caption': '인스타 글', 'permalink': 'https://i/901', 'timestamp': '2026-09-20T01:00:00+0000'}
        raise AssertionError(f'unexpected call {path} {params}')


@override_settings(MARKETING=CFG)
class CollectTest(TestCase):
    def test_only_hantijae_ads_are_saved_and_others_leave_no_trace(self):
        g = Graph()
        report = ads.collect(TODAY, get=g)
        self.assertEqual((report.found, report.ours, report.new, report.unknown), (3, 2, 2, 0))
        self.assertEqual(sorted(Ad.objects.values_list('ad_id', 'channel', 'post_id', 'ig_media_id')),
                         [('1', 'facebook', '111_10', '900'), ('3', 'instagram', '901', '901')])
        first = g.calls[0]
        self.assertEqual((first[0], first[1]['fields'], first[1]['access_token']), ('act_1/insights', 'ad_id', 'atok'))
        for path, params in g.calls:   # 다른 광고(2)에는 게시물 번호 말고 아무 칸도 요청하지 않는다
            self.assertNotIn('name', params.get('fields', ''))
        [listing] = [q for p, q in g.calls if p == 'act_1/ads']
        self.assertEqual(listing['fields'], 'id,' + ads.CREATIVE)
        daily = [q for p, q in g.calls if p == 'act_1/insights' and 'time_increment' in q][0]
        self.assertEqual(json.loads(daily['filtering']), [{'field': 'ad.id', 'operator': 'IN', 'value': ['1', '3']}])
        self.assertFalse(any(p.startswith('2/') for p, _ in g.calls))

    def test_page_token_reads_posts_and_owners_ads_token_reads_ads(self):
        g = Graph()
        ads.collect(TODAY, get=g)
        for path, params in g.calls:
            want = 'ptok' if params.get('fields', '').split(',')[0] in ('owner', 'message', 'caption') else 'atok'
            self.assertEqual(params['access_token'], want, path)

    def test_daily_numbers_are_parsed_and_overwritten(self):
        ads.collect(TODAY, get=Graph())
        d = AdDay.objects.get(ad__ad_id='1')
        self.assertEqual((d.day, d.spend, d.impressions, d.clicks, d.link_clicks, d.reactions, d.engagement),
                         (date(2026, 9, 22), 30000, 1000, 100, 7, 60, 120))
        ads.collect(TODAY, get=Graph(days=[day_row('1', '2026-09-22', '29000')]))
        self.assertEqual(AdDay.objects.get(ad__ad_id='1').spend, 29000)

    def test_missing_actions_count_as_zero(self):
        row = day_row('1', '2026-09-22')
        del row['actions']
        ads.collect(TODAY, get=Graph(days=[row]))
        self.assertEqual(AdDay.objects.get(ad__ad_id='1').reactions, 0)

    def test_totals_hold_reach_and_first_last_spend_day(self):
        g = Graph(days=[day_row('1', '2026-09-22'), day_row('1', '2026-09-30'), day_row('1', '2026-10-01', '0')])
        ads.collect(TODAY, get=g)
        ad = Ad.objects.get(ad_id='1')
        self.assertEqual((ad.spend, ad.reach, ad.clicks, ad.link_clicks, ad.reactions),
                         (30000, 6000, 1200, 50, 500))
        self.assertEqual((ad.first_day, ad.last_day), (date(2026, 9, 22), date(2026, 9, 30)))   # 지출 0인 날은 빼고
        self.assertIsNotNone(ad.totals_at)

    def test_a_failing_total_keeps_yesterdays_numbers(self):
        ads.collect(TODAY, get=Graph())
        with self.assertLogs('intake', level='WARNING'):
            ads.collect(TODAY, get=Graph(totals={'1': {'spend': '1'}}, broken={'1/insights'}))
        self.assertEqual(Ad.objects.get(ad_id='1').reach, 6000)

    def test_instagram_owner_check_failing_on_the_token_is_unknown_not_dropped(self):
        with self.assertLogs('intake', level='WARNING'):
            report = ads.collect(TODAY, get=Graph(owners={'901': 190}))
        self.assertEqual((report.unknown, Ad.objects.filter(ad_id='3').exists()), (1, False))
        ads.collect(TODAY, get=Graph())
        self.assertTrue(Ad.objects.filter(ad_id='3').exists())

    def test_someone_elses_instagram_post_is_not_ours(self):
        report = ads.collect(TODAY, get=Graph(owners={'901': '999'}))
        self.assertEqual((report.ours, Ad.objects.filter(ad_id='3').exists()), (1, False))

    def test_someone_elses_instagram_post_answering_error_100_is_not_ours_and_quiet(self):
        with self.assertNoLogs('intake', level='WARNING'):
            report = ads.collect(TODAY, get=Graph(owners={'901': 100}))
        self.assertEqual((report.ours, report.unknown, Ad.objects.filter(ad_id='3').exists()), (1, 0, False))

    def test_refresh_does_not_overwrite_card_or_book_changed_meanwhile(self):
        ads.collect(TODAY, get=Graph())
        stale = Ad.objects.get(ad_id='1')   # 몇 분 전에 읽은 행
        book = make_book(title='다른 책', isbn='979-11-00000-02-2')
        Ad.objects.filter(ad_id='1').update(card=Ad.SENT, book=book)
        ads._refresh(Graph(), CFG, stale)
        fresh = Ad.objects.get(ad_id='1')
        self.assertEqual((fresh.card, fresh.book, fresh.reach), (Ad.SENT, book, 6000))

    def test_known_ads_are_not_classified_again(self):
        ads.collect(TODAY, get=Graph())
        g = Graph()
        ads.collect(TODAY, get=g)
        ads_calls = [q for p, q in g.calls if p == 'act_1/ads']
        self.assertEqual([json.loads(q['filtering'])[0]['value'] for q in ads_calls], [['2']])   # 저장 안 한 다른 광고만 다시 본다

    def test_book_comes_from_the_bots_placement_first(self):
        book = make_book(title='농부, 짠한 형')
        p = Proposal.objects.create(kind=Proposal.NOW, book=book, headline='x')
        Draft.objects.create(proposal=p, channel=Draft.INSTAGRAM, body='b', status=Draft.POSTED,
                             placements=[{'kind': 'facebook', 'id': '111_10', 'label': 'x', 'url': 'u', 'at': ''}])
        make_book(title='나는 산속으로 더 깊이 들어간다', isbn='979-11-00000-01-1')
        ads.collect(TODAY, get=Graph())
        self.assertEqual(Ad.objects.get(ad_id='1').book, book)

    def test_book_from_the_post_text_only_when_one_title_matches(self):
        sansok = make_book()
        ads.collect(TODAY, get=Graph())
        self.assertEqual(Ad.objects.get(ad_id='1').book, sansok)
        self.assertIsNone(Ad.objects.get(ad_id='3').book)   # '인스타 글' — 맞는 제목 없음

    def test_full_range_reads_days_on_each_ad_itself_without_filtering(self):
        g = Graph()
        ads.collect(TODAY, full=True, get=g)
        daily = [(p, q) for p, q in g.calls if p.endswith('/insights') and 'time_increment' in q]
        self.assertEqual([p for p, _ in daily], ['1/insights', '3/insights'])
        for _, q in daily:
            self.assertEqual((q['time_increment'], q['date_preset'], 'filtering' in q), (1, 'maximum', False))
        self.assertFalse(any(p == 'act_1/insights' and 'time_increment' in q for p, q in g.calls))
        self.assertEqual(AdDay.objects.count(), 2)

    def test_daily_run_still_reads_days_on_the_account_with_filtering(self):
        g = Graph()
        ads.collect(TODAY, get=g)
        [(p, q)] = [(p, q) for p, q in g.calls if p.endswith('/insights') and 'time_increment' in q]
        self.assertEqual(p, 'act_1/insights')
        self.assertEqual(json.loads(q['filtering'])[0]['field'], 'ad.id')

    def test_an_ad_missing_from_the_listing_is_read_on_its_own_and_saved(self):
        g = Graph(unlisted=('1',))
        report = ads.collect(TODAY, get=g)
        self.assertEqual((report.new, report.unlisted, Ad.objects.filter(ad_id='1').exists()), (2, 0, True))
        own = [q for p, q in g.calls if p == '1']
        self.assertEqual([q['fields'] for q in own], [ads.CREATIVE])   # 글 번호 칸 말고는 요청하지 않는다
        self.assertEqual(own[0]['access_token'], 'atok')

    def test_an_unlisted_ad_that_cannot_be_read_is_counted_and_skipped(self):
        g = Graph(unlisted=('1',), unreadable=('1',))
        with self.assertLogs('intake', level='WARNING') as logs:
            report = ads.collect(TODAY, get=g)
        self.assertEqual((report.unlisted, report.new, Ad.objects.filter(ad_id='1').exists()), (1, 1, False))
        self.assertEqual(logs.output, ['WARNING:intake:ads creative: HTTP 400 code 100'])
        self.assertIn('목록에 없어 따로 못 읽은 광고 1개', ads.report_text(report))

    def test_an_unlisted_ad_hitting_an_auth_error_goes_up(self):
        g = Graph(unlisted=('1',))
        base = g.answer
        g.route = lambda path, params: err(190) if path == '1' else base(path, params)
        with self.assertRaises(meta.MetaAuthError):
            ads.collect(TODAY, get=g)

    def test_an_unlisted_ad_with_a_permission_error_is_skipped_not_fatal(self):
        g = Graph(unlisted=('1',))
        base = g.answer
        g.route = lambda path, params: err(200) if path == '1' else base(path, params)
        with self.assertLogs('intake', level='WARNING') as logs:
            report = ads.collect(TODAY, get=g)
        self.assertEqual((report.unlisted, report.new, Ad.objects.filter(ad_id='1').exists()), (1, 1, False))
        self.assertEqual(logs.output, ['WARNING:intake:ads creative: HTTP 400 code 200'])

    def test_token_errors_go_up(self):
        g = FakeGraph(lambda path, params: err(190))
        with self.assertRaises(meta.MetaAuthError):
            ads.collect(TODAY, get=g)

    def test_unreadable_post_is_retried_next_day_not_saved_blank(self):
        only = {'1': {'effective_object_story_id': '111_10'}}
        with self.assertLogs('intake', level='WARNING'):
            report = ads.collect(TODAY, get=Graph(found=('1',), creatives=only, post_errors={'111_10': 190}))
        self.assertEqual((report.unknown, Ad.objects.filter(ad_id='1').exists()), (1, False))
        ads.collect(TODAY, get=Graph(found=('1',), creatives=only))
        self.assertIn('2쇄', Ad.objects.get(ad_id='1').post_text)

    def test_post_gone_is_saved_blank_so_spend_is_kept(self):
        only = {'1': {'effective_object_story_id': '111_10'}}
        with self.assertLogs('intake', level='WARNING'):
            report = ads.collect(TODAY, get=Graph(found=('1',), creatives=only, post_errors={'111_10': 100}))
        ad = Ad.objects.get(ad_id='1')
        self.assertEqual((report.unknown, ad.post_text, ad.book), (0, '', None))

    def test_book_matches_full_text_but_only_200_characters_are_stored(self):
        sansok = make_book()
        only = {'1': {'effective_object_story_id': '111_10'}}
        text = 'x' * 200 + ' 『나는 산속으로 더 깊이 들어간다』'
        ads.collect(TODAY, get=Graph(found=('1',), creatives=only, post_text=text))
        ad = Ad.objects.get(ad_id='1')
        self.assertEqual((ad.book, len(ad.post_text)), (sansok, 200))

    @override_settings(MARKETING={**CFG, 'META_ADS_TOKEN': ''})
    def test_without_config_reads_nothing(self):
        g = Graph()
        self.assertEqual(ads.collect(TODAY, get=g).found, 0)
        self.assertEqual(g.calls, [])

    @override_settings(MARKETING={**CFG, 'META_ADS_EXPIRES': '11/30'})
    def test_bad_expiry_is_none_and_logged(self):
        with self.assertLogs('intake', level='WARNING'):
            self.assertIsNone(ads.expires_on())


@override_settings(MARKETING=CFG)
class RunTest(TestCase):
    def setUp(self):
        self.notes = []

    def test_success_marks_the_day(self):
        self.assertIsNotNone(ads.run(TODAY, self.notes.append, get=Graph()))
        self.assertEqual(WorkerState.get('ads_ok_on'), '2026-10-03')

    def test_expiry_reminded_seven_days_before_and_the_day_before_once_each(self):
        for day in (date(2026, 11, 22), date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 29), date(2026, 11, 29)):
            ads.run(day, self.notes.append, get=Graph())
        self.assertEqual(len([n for n in self.notes if '11월 30일' in n and '갱신' in n]), 2)
        self.assertNotIn('11월 22일', ' '.join(self.notes))

    def test_a_new_expiry_reminds_again(self):
        ads.run(date(2026, 11, 23), self.notes.append, get=Graph())
        with self.settings(MARKETING={**CFG, 'META_ADS_EXPIRES': '2027-01-29'}):
            ads.run(date(2027, 1, 22), self.notes.append, get=Graph())
        self.assertEqual(len(self.notes), 2)

    def test_both_reminders_due_at_once_send_one_note(self):
        ads.run(date(2026, 11, 29), self.notes.append, get=Graph())
        ads.run(date(2026, 11, 30), self.notes.append, get=Graph())
        self.assertEqual(len(self.notes), 1)

    def test_first_run_after_expiry_says_it_has_ended(self):
        ads.run(date(2026, 12, 1), self.notes.append, get=Graph())
        self.assertEqual(len(self.notes), 1)
        self.assertIn('11월 30일에 끝났어요', self.notes[0])

    def test_reminder_goes_out_even_when_collecting_fails(self):
        ads.run(date(2026, 11, 23), self.notes.append, get=FakeGraph(lambda p, q: err(190)))
        self.assertTrue(any('11월 30일' in n for n in self.notes))

    def test_token_error_tells_to_renew_once_a_day(self):
        g = FakeGraph(lambda p, q: err(190))
        self.assertIsNone(ads.run(TODAY, self.notes.append, get=g))
        ads.run(TODAY, self.notes.append, get=g)
        self.assertEqual(self.notes, [ads.TOKEN_NOTE])
        self.assertIsNone(WorkerState.get('ads_ok_on'))

    def test_permission_error_points_at_the_ad_account_role(self):
        ads.run(TODAY, self.notes.append, get=FakeGraph(lambda p, q: err(200)))
        self.assertEqual(self.notes, [ads.ROLE_NOTE])
        self.assertIn('분석자', ads.ROLE_NOTE)

    def test_one_old_ads_permission_error_does_not_send_the_role_note(self):
        g = Graph(unlisted=('1',))
        base = g.answer
        g.route = lambda path, params: err(200) if path == '1' else base(path, params)
        with self.assertLogs('intake', level='WARNING'):
            report = ads.run(TODAY, self.notes.append, get=g)
        self.assertIsNotNone(report)
        self.assertEqual(WorkerState.get('ads_ok_on'), '2026-10-03')
        self.assertNotIn(ads.ROLE_NOTE, self.notes)

    @override_settings(MARKETING={})
    def test_without_config_does_nothing(self):
        self.assertIsNone(ads.run(TODAY, self.notes.append, get=Graph()))
        self.assertEqual(self.notes, [])


ADMIN, GROUP = 100, -200
SEPT = [date(2026, 9, 22) + timedelta(days=i) for i in range(7)]   # 9/22~28


def at(month, day, hour=9, minute=30):
    return datetime(2026, month, day, hour, minute, tzinfo=KST)


def organic(reactions, post_id):
    return ChannelPost('facebook', datetime(2026, 9, 10, tzinfo=dt_tz.utc), '글', 'u', reactions, 0, 0, id=post_id)


class CardTest(TestCase):
    def setUp(self):
        WorkerState.put('bnk_mode', 'on')
        WorkerState.put('ads_card_mode', 'live')
        self.book = make_book()
        self.tg = FakeTG()
        self.bot = SimpleNamespace(tg=self.tg, marketing=SimpleNamespace(mode=lambda: 'live'),
                                   review_chat_id=lambda: GROUP, _chat=lambda kind: ADMIN)
        self.fetch = lambda since, until: {'facebook': [organic(10, '111_5'), organic(18, '111_6'), organic(30, '111_7'),
                                                        organic(600, '111_1')], 'instagram': []}

    def read_bnk(self, start, end):
        d = start
        while d <= end:
            BnkDay.objects.create(day=d, read_on=d + timedelta(days=2))
            d += timedelta(days=1)

    def sept_ad(self, ad_id='1', post_id='111_1', book='default', days=SEPT, **kw):
        fields = dict(spend=35000, reach=7000, clicks=1200, link_clicks=50, reactions=500)
        fields.update(kw)
        return make_ad(ad_id=ad_id, post_id=post_id, book=self.book if book == 'default' else book, days=days,
                       daily=5000, **fields)

    def send(self, when):
        WorkerState.put('ads_ok_on', when.astimezone(KST).date().isoformat())
        return ads.send_due_cards(self.bot, when, fetch=self.fetch)

    def test_no_card_unless_todays_collection_succeeded(self):
        self.sept_ad(book=None)
        WorkerState.put('ads_ok_on', '2026-09-30')
        self.assertEqual(ads.send_due_cards(self.bot, at(10, 1), fetch=self.fetch), 0)
        self.assertEqual(self.tg.sent('send'), [])
        self.assertEqual(Ad.objects.get().card, Ad.PENDING)
        WorkerState.put('ads_ok_on', '2026-10-01')
        self.assertEqual(ads.send_due_cards(self.bot, at(10, 1), fetch=self.fetch), 1)

    def test_ended_ad_waits_for_sales_then_one_card_with_plain_numbers(self):
        ad = self.sept_ad()
        self.read_bnk(date(2026, 8, 26), date(2026, 9, 27))
        self.assertEqual(self.send(at(10, 1)), 0)   # 9/28 판매가 아직 다 안 들어옴
        BnkDay.objects.create(day=date(2026, 9, 28), read_on=date(2026, 9, 30))
        make_sale(date(2026, 9, 23), 2, self.book)
        make_sale(date(2026, 9, 25), 1, self.book)
        self.assertEqual(self.send(at(10, 1)), 1)
        [card] = self.tg.sent('send')
        self.assertEqual((card['chat'], card['html']), (GROUP, True))
        for part in ('📣 광고 결과', '『나는 산속으로 더 깊이 들어간다』 글', '(페이스북)', '9월 22일~28일 · 7일 · 35,000원',
                     '7,000명에게 보였어요 (1,000원에 200명)', '광고에 붙은 링크·버튼을 누른 횟수 50번', '반응(좋아요 등) 500',
                     '광고 없는 평소 페북 글은 보통 반응 18', '광고 전 7일 0권 → 광고 7일 3권', ads.CARD_NOTE):
            self.assertIn(part, card['text'])
        self.assertNotIn('1,200', card['text'])   # Meta '클릭(전체)'은 싣지 않는다
        ad.refresh_from_db()
        self.assertEqual((ad.card, ad.card_sent_at), (Ad.SENT, at(10, 1)))

    def test_not_ended_until_three_days_without_spend(self):
        self.sept_ad(book=None)
        self.assertEqual(self.send(at(9, 30)), 0)
        self.assertEqual(self.send(at(10, 1)), 1)

    def test_admin_only_goes_to_the_admin_and_off_sends_nothing(self):
        self.sept_ad(book=None)
        WorkerState.put('ads_card_mode', 'off')
        self.assertEqual(self.send(at(10, 1)), 0)
        WorkerState.put('ads_card_mode', 'admin_only')
        self.send(at(10, 1))
        self.assertEqual(self.tg.sent('send')[0]['chat'], ADMIN)

    def test_live_waits_for_marketing_live(self):
        self.sept_ad(book=None)
        self.bot.marketing = SimpleNamespace(mode=lambda: 'admin_only')
        self.send(at(10, 1))
        self.assertEqual(self.tg.sent('send')[0]['chat'], ADMIN)

    def test_card_goes_without_sales_after_ten_days(self):
        self.sept_ad()
        self.assertEqual(self.send(at(10, 7)), 0)
        self.assertEqual(self.send(at(10, 8)), 1)
        self.assertNotIn('· 전산망 판매 『', self.tg.sent('send')[0]['text'])   # 출처 문구에도 '전산망 판매'가 있다
        self.assertNotIn(ads.CARD_NOTE, self.tg.sent('send')[0]['text'])

    def test_bnk_off_does_not_hold_the_card(self):
        WorkerState.put('bnk_mode', 'off')
        self.sept_ad()
        self.assertEqual(self.send(at(10, 1)), 1)

    def test_sales_records_starting_too_late_are_said_not_guessed(self):
        self.sept_ad()
        self.read_bnk(date(2026, 9, 20), date(2026, 9, 28))   # 앞 기간(9/15~21)보다 늦게 시작
        self.send(at(10, 1))
        text = self.tg.sent('send')[0]['text']
        self.assertIn('판매는 기록이 그보다 늦게 시작돼 비교하지 못했어요', text)
        self.assertNotIn('권 →', text)

    def test_unknown_book_says_why_sales_are_missing(self):
        self.sept_ad(book=None, post_text='가을 북토크 안내합니다')
        self.send(at(10, 1))
        text = self.tg.sent('send')[0]['text']
        self.assertIn('「가을 북토크 안내합니다」 글', text)
        self.assertIn('어느 책 광고인지 몰라 판매는 뺐어요', text)

    def test_two_ads_for_one_book_share_one_sales_line(self):
        self.read_bnk(date(2026, 8, 26), date(2026, 9, 28))
        self.sept_ad()
        self.sept_ad(ad_id='2', post_id='111_2')
        self.send(at(10, 1))
        self.assertEqual(self.tg.sent('send')[0]['text'].count('· 전산망 판매 『'), 1)

    def test_three_ads_a_message_and_the_rest_the_next_day(self):
        WorkerState.put('bnk_mode', 'off')
        for i in range(4):
            self.sept_ad(ad_id=str(i + 1), post_id=f'111_{i + 1}')
        self.assertEqual((self.send(at(10, 1)), self.send(at(10, 1, 15))), (1, 0))   # 하루 한 메시지
        self.assertEqual(self.tg.sent('send')[0]['text'].count('35,000원'), 3)
        self.assertEqual(self.send(at(10, 2)), 1)
        self.assertEqual(Ad.objects.filter(card=Ad.SENT).count(), 4)

    def test_turning_cards_on_late_skips_old_ads(self):
        old = self.sept_ad(days=[date(2026, 9, 1), date(2026, 9, 5)], book=None)
        WorkerState.put('ads_card_mode', 'off')
        self.send(at(9, 20))
        WorkerState.put('ads_card_mode', 'live')
        self.assertEqual(self.send(at(9, 20)), 0)
        old.refresh_from_db()
        self.assertEqual(old.card, Ad.SKIPPED)

    def test_only_between_0930_and_2100(self):
        self.sept_ad(book=None)
        self.assertEqual(self.send(at(10, 1, 9, 29)), 0)
        self.assertEqual(self.send(at(10, 1, 21, 0)), 0)
        self.assertEqual(self.send(at(10, 1, 20, 59)), 1)

    def test_past_ads_baseline_needs_three(self):
        self.sept_ad(book=None)
        for i, (spend, reach) in enumerate([(20000, 4000), (30000, 6300), (15000, 3000)]):
            make_ad(ad_id=f'p{i}', post_id=f'111_p{i}', days=[date(2026, 6, 1)], spend=spend, reach=reach,
                    card=Ad.SENT)
        self.send(at(10, 1))
        self.assertIn('지난 한티재 광고 3개는 보통 1,000원에 200명에게 보였어요', self.tg.sent('send')[0]['text'])

    def test_too_few_organic_posts_or_a_failed_read_leave_that_line_out(self):
        self.sept_ad(book=None)
        self.fetch = lambda since, until: (_ for _ in ()).throw(RuntimeError('x'))
        with self.assertLogs('intake', level='WARNING'):
            self.send(at(10, 1))
        self.assertNotIn('평소 페북 글', self.tg.sent('send')[0]['text'])

    def test_a_failed_send_keeps_the_ad_waiting(self):
        self.sept_ad(book=None)
        self.tg.send_message = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('telegram down'))
        with self.assertRaises(RuntimeError):
            self.send(at(10, 1))
        self.assertEqual((Ad.objects.get().card, WorkerState.get('ads_card_day')), (Ad.PENDING, None))

    def test_a_failed_send_is_not_retried_for_thirty_minutes(self):
        self.sept_ad(book=None)
        calls = []
        self.fetch = lambda since, until: calls.append(1) or {'facebook': [], 'instagram': []}
        sent = self.tg.send_message
        self.tg.send_message = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('telegram down'))
        with self.assertRaises(RuntimeError):
            self.send(at(10, 1, 10, 0))
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.send(at(10, 1, 10, 10)), 0)   # 10분 뒤: 만들지도 보내지도 않는다
        self.assertEqual(len(calls), 1)
        self.tg.send_message = sent
        self.assertEqual(self.send(at(10, 1, 10, 31)), 1)   # 31분 뒤: 다시 시도
        self.assertEqual(len(calls), 2)
        self.assertEqual(WorkerState.get('ads_card_day'), '2026-10-01')


class BriefingHelpersTest(TestCase):
    def test_week_text_counts_only_that_weeks_days(self):
        make_ad(post_id='111_1', days=[date(2026, 9, 26), date(2026, 9, 27), date(2026, 9, 28)], book=None,
                post_text='농부 이야기')
        self.assertEqual(ads.week_text(date(2026, 9, 28), date(2026, 10, 4)), '지난주 광고: 「농부 이야기」 글 1일 · 5,000원')

    def test_week_text_names_two_and_counts_the_rest(self):
        for i, daily in enumerate((3000, 9000, 6000)):
            make_ad(ad_id=str(i), post_id=f'111_{i}', days=[date(2026, 9, 29)], daily=daily, post_text=f'글{i}')
        text = ads.week_text(date(2026, 9, 28), date(2026, 10, 4))
        self.assertTrue(text.startswith('지난주 광고: 「글1」 글 1일 · 9,000원, 「글2」 글'))
        self.assertTrue(text.endswith(' 외 1건'))

    def test_measure_note_sums_two_ads_on_the_same_post(self):
        make_ad(ad_id='1', post_id='111_9', days=[date(2026, 9, 22), date(2026, 9, 23)])
        make_ad(ad_id='2', post_id='111_9', days=[date(2026, 9, 23), date(2026, 9, 24)])
        self.assertEqual(ads.measure_note({'111_9', ''}), '(광고 3일 · 20,000원 포함)')
        self.assertEqual(ads.post_ids(), {'111_9'})
        self.assertEqual(ads.measure_note({'111_8'}), '')


class MonthLinesTest(TestCase):
    def test_month_lines_split_an_ad_across_months(self):
        make_ad(post_id='111_1', book=make_book(), days=[date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1)],
                reach=6000)
        self.assertEqual(ads.month_lines(date(2026, 9, 1), date(2026, 9, 30)),
                         ['광고 1건 · 광고비 10,000원',
                          '『나는 산속으로 더 깊이 들어간다』 글: 2일 · 10,000원 · 지금까지 6,000명에게 보였어요'])
        self.assertEqual(ads.month_lines(date(2026, 10, 1), date(2026, 10, 31))[0], '광고 1건 · 광고비 5,000원')
        self.assertEqual(ads.month_lines(date(2026, 8, 1), date(2026, 8, 31)), [])

    def test_more_than_three_ads_are_summed(self):
        for i in range(5):
            make_ad(ad_id=str(i), post_id=f'111_{i}', days=[date(2026, 9, 10)], daily=1000 * (i + 1), post_text=f'글{i}')
        lines = ads.month_lines(date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual((len(lines), lines[0], lines[-1]), (5, '광고 5건 · 광고비 15,000원', '외 2건 3,000원'))

    def test_sales_ride_along_when_ready(self):
        WorkerState.put('bnk_mode', 'on')
        book = make_book()
        make_ad(book=book, days=SEPT)
        d = date(2026, 8, 26)
        while d <= date(2026, 9, 28):
            BnkDay.objects.create(day=d, read_on=d + timedelta(days=2))
            d += timedelta(days=1)
        make_sale(date(2026, 9, 23), 3, book)
        self.assertIn('전산망 판매 광고 전 7일 0권 → 광고 7일 3권', ads.month_lines(date(2026, 9, 1), date(2026, 9, 30))[1])


@override_settings(MARKETING=CFG)
class AdsCommandTest(TestCase):
    def setUp(self):
        self.tg = FakeTG()
        self.m = Marketing(self.tg, FakeLLM({}), FakeHost())

    def reply(self, arg):
        self.m.admin_command(ADMIN, '/ads', arg, now=at(10, 3, 10, 0))
        return self.tg.sent('send')[-1]['text']

    def test_card_switch(self):
        self.assertEqual(self.reply('card admin_only'), 'ads_card_mode=admin_only')
        self.assertEqual(WorkerState.get('ads_card_mode'), 'admin_only')

    def test_status_shows_expiry_switch_and_recent_ads_by_book(self):
        make_ad(book=make_book(), days=SEPT, spend=35000, reach=7000)
        text = self.reply('')
        for part in ('광고 토큰 만료 2026-11-30', 'ads_card_mode=off', '『나는 산속으로 더 깊이 들어간다』 글 9월 22일~28일 35,000원',
                     '/ads card'):
            self.assertIn(part, text)

    def test_now_collects_and_marks_the_day(self):
        with mock.patch('marketing.ads.collect', return_value=ads.Report(found=3, ours=2, new=1, days=9)):
            text = self.reply('now')
        self.assertEqual(text, '기간에 돈 광고 3개 중 한티재 광고 2개(새로 1개) · 일별 9줄')
        self.assertEqual(WorkerState.get('marketing_last_ads_scan'), '2026-10-03')

    def test_now_reports_meta_errors_without_details(self):
        with mock.patch('marketing.ads.collect', side_effect=meta.MetaError('HTTP 500 code 2', 2)):
            self.assertEqual(self.reply('now'), '광고 성과 조회 실패: HTTP 500 code 2')

    def test_now_passes_the_bots_ai_for_book_linking(self):
        with mock.patch('marketing.ads.run', return_value=ads.Report()) as run:
            self.reply('now')
        self.assertIs(run.call_args.kwargs['llm'], self.m.llm)

    @override_settings(MARKETING={})
    def test_now_without_config(self):
        self.assertIn('설정이 없어요', self.reply('now'))


@override_settings(MARKETING=CFG)
class BackfillTest(TestCase):
    def test_backfill_reads_everything_once_and_prints_counts_only(self):
        out = StringIO()
        with mock.patch('marketing.ads.collect', return_value=ads.Report(found=146, ours=5, new=5, days=40)) as c:
            make_ad(days=[date(2026, 3, 2), date(2026, 3, 5)], spend=20000)
            call_command('marketing_ads_backfill', stdout=out)
        self.assertTrue(c.call_args.kwargs['full'])
        text = out.getvalue()
        self.assertIn('기간에 돈 광고 146개 중 한티재 광고 5개', text)
        self.assertIn('저장된 한티재 광고 1개 · 2026-03-02~2026-03-05 · 합계 20,000원', text)
        self.assertIn('카드 없이 둔 지난 광고 1개', text)
        self.assertEqual(Ad.objects.get().card, Ad.SKIPPED)

    @override_settings(MARKETING={})
    def test_backfill_needs_config(self):
        with self.assertRaises(CommandError):
            call_command('marketing_ads_backfill', stdout=StringIO())
