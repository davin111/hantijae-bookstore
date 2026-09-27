import json
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.test import TestCase, override_settings

from intake import funding, notices, pipeline
from intake.bot import Bot
from intake.deps import Deps
from intake.models import FundingCampaign, TelegramChat, WorkerState
from intake.tests.test_bot import ADMIN, CONFIG, GROUP, FakeLLM, FakeTG, msg
from web.models import Notice

NOW = datetime(2026, 9, 28, 3, 0, tzinfo=dt_timezone.utc)
KST = notices.KST
ALADIN_LIST = ('<li><a href="/m/bookfund/view.aspx?pid=3013"><img></a></li>'
               '<li><a href="/m/bookfund/view.aspx?pid=3012">다른 책</a></li><a href="/m/bookfund/view.aspx?pid=3013">중복</a>')


def aladin_view(publisher='한티재', title='농부, 짠한 형 - 두물머리 농사꾼의 농업 비평', end='2026-10-11', label='펴낸곳'):
    return (f'<meta property="og:title" content="{title}" />'
            f'<div class="fd_dday"><span class="dday_t2">펀딩 중</span> (마감 {end}, 출간예정 2026-10-19)</div>'
            f'<ul><li>도서명: &lt;농부, 짠한 형&gt;</li><li>{label}: {publisher}</li><li>판형: 127*200mm / 216쪽</li></ul>')


TUMBLBUG = json.dumps({'status': '200 OK', 'body': {'result': {'projects': [
    {'permalink': 'proudhon', 'title': '<프루동 평전> 국내 최초 번역 출판',
     'fundingStartDate': '2021-04-13T20:38:21', 'endDate': '2021-05-24T23:59:59', 'isEnded': True},
    {'permalink': 'newbook', 'title': '새 책 펀딩', 'fundingStartDate': '2026-09-20T10:00:00',
     'endDate': '2026-10-20T23:59:59', 'isEnded': False},
    {'permalink': 'soon', 'title': '공개 예정', 'fundingStartDate': '2026-11-01T10:00:00',
     'endDate': '2026-12-01T23:59:59', 'isEnded': False},
]}}}, ensure_ascii=False)
PAGES = {funding.ALADIN_LIST_URL: ALADIN_LIST, funding.ALADIN_VIEW_URL.format(pid=3013): aladin_view(),
         funding.ALADIN_VIEW_URL.format(pid=3012): aladin_view(publisher='다른출판사'), funding.TUMBLBUG_LIST_URL: TUMBLBUG}


class FakeGet:
    def __init__(self, pages, broken=()):
        self.pages, self.broken, self.calls = pages, broken, []

    def __call__(self, url):
        self.calls.append(url)
        if url in self.broken or url not in self.pages:
            raise OSError(f'unreachable {url}')
        return self.pages[url]


class ParseTest(TestCase):
    def test_aladin_list_pids_unique_newest_first(self):
        self.assertEqual(funding.aladin_pids(ALADIN_LIST), ['3013', '3012'])

    def test_parse_aladin_view(self):
        ours = funding.parse_aladin_view('3013', aladin_view())
        self.assertTrue(ours.is_ours)
        self.assertEqual(ours.title, '농부, 짠한 형 - 두물머리 농사꾼의 농업 비평')
        self.assertEqual(ours.ends_at, datetime(2026, 10, 12, 0, 0, tzinfo=KST))
        self.assertFalse(funding.parse_aladin_view('3012', aladin_view(publisher='다른출판사')).is_ours)
        broken = funding.parse_aladin_view('1', '<html></html>')
        self.assertEqual((broken.publisher, broken.is_ours, broken.ends_at), ('', False, None))
        self.assertFalse(broken.mentions_publisher)

    def test_parse_aladin_view_accepts_label_variants(self):
        # 실제 알라딘 페이지는 '펴낸곳:', '펴낸 곳:'(띄어씀), '출판사:' 를 섞어 쓴다 — 셋 다 읽어야 한다.
        space_label = funding.parse_aladin_view('1', aladin_view(publisher='북극곰', label='펴낸 곳'))
        self.assertEqual(space_label.publisher, '북극곰')
        self.assertFalse(space_label.is_ours)
        publisher_label = funding.parse_aladin_view('1', aladin_view(publisher='다산어린이', label='출판사'))
        self.assertEqual(publisher_label.publisher, '다산어린이')
        ours_with_space_label = funding.parse_aladin_view('1', aladin_view(publisher='한티재', label='펴낸 곳'))
        self.assertTrue(ours_with_space_label.is_ours)

    def test_parse_aladin_view_mentions_publisher_without_label(self):
        # 펴낸곳/출판사 라벨이 없어도 본문에 한티재가 언급되면 표시해 둔다 — 우리 것 아님으로 바로 단정하지 않기 위해서다.
        mentioned = funding.parse_aladin_view('1', '<meta property="og:title" content="새 책" />한티재의 새 책입니다, 펴낸곳 표시가 없는 페이지')
        self.assertEqual(mentioned.publisher, '')
        self.assertTrue(mentioned.mentions_publisher)
        not_mentioned = funding.parse_aladin_view('1', '<meta property="og:title" content="이벤트 공지" />별다른 정보 없음')
        self.assertEqual(not_mentioned.publisher, '')
        self.assertFalse(not_mentioned.mentions_publisher)

    def test_parse_tumblbug_and_liveness(self):
        found = {f.external_id: f for f in funding.parse_tumblbug(TUMBLBUG)}
        self.assertEqual(found['newbook'].url, 'https://tumblbug.com/newbook')
        self.assertEqual(found['newbook'].ends_at, datetime(2026, 10, 21, 0, 0, tzinfo=KST))
        self.assertTrue(funding.is_live(found['newbook'], NOW))
        self.assertFalse(funding.is_live(found['proudhon'], NOW))
        self.assertFalse(funding.is_live(found['soon'], NOW))

    def test_campaign_message(self):
        a = FundingCampaign(platform='aladin', title='농부, 짠한 형 - 두물머리 농사꾼의 농업 비평',
                            ends_at=datetime(2026, 10, 12, 0, 0, tzinfo=KST))
        self.assertEqual(notices.campaign_message(a), '『농부, 짠한 형』 알라딘 북펀드 진행 중 · 10월 11일까지')
        t = FundingCampaign(platform='tumblbug', title='새 책 펀딩', ends_at=datetime(2026, 10, 21, 0, 0, tzinfo=KST))
        self.assertEqual(notices.campaign_message(t), '새 책 펀딩 텀블벅 펀딩 진행 중 · 10월 20일까지')
        long = FundingCampaign(platform='tumblbug', title='가' * 80, ends_at=datetime(2026, 10, 21, tzinfo=KST))
        self.assertLessEqual(len(notices.campaign_message(long)), 60)


class ScanTest(TestCase):
    def test_scan_records_everything_and_returns_live_ours(self):
        result = funding.scan(get=FakeGet(PAGES), now=NOW, sleep=lambda s: None)
        self.assertEqual(result.errors, [])
        self.assertEqual(sorted((c.platform, c.external_id) for c in result.new),
                         [('aladin', '3013'), ('tumblbug', 'newbook')])
        self.assertEqual(FundingCampaign.objects.filter(platform='aladin').count(), 2)
        self.assertFalse(FundingCampaign.objects.filter(external_id='soon').exists())   # 공개 예정은 나중에 다시

    def test_second_scan_skips_seen_pages(self):
        funding.scan(get=FakeGet(PAGES), now=NOW, sleep=lambda s: None)
        get = FakeGet(PAGES)
        self.assertEqual(funding.scan(get=get, now=NOW, sleep=lambda s: None).new, [])
        self.assertNotIn(funding.ALADIN_VIEW_URL.format(pid=3013), get.calls)

    def test_errors_are_per_platform(self):
        result = funding.scan(get=FakeGet(PAGES, broken={funding.ALADIN_LIST_URL}), now=NOW, sleep=lambda s: None)
        self.assertEqual(result.errors, ['알라딘 북펀드: OSError'])
        self.assertEqual([c.external_id for c in result.new], ['newbook'])

    def test_empty_aladin_list_is_reported(self):
        result = funding.scan(get=FakeGet(dict(PAGES, **{funding.ALADIN_LIST_URL: '<html></html>'})), now=NOW,
                              sleep=lambda s: None)
        self.assertEqual(result.errors, ['알라딘 북펀드: ValueError'])

    def test_unreadable_view_is_retried_next_time(self):
        pages = dict(PAGES)
        del pages[funding.ALADIN_VIEW_URL.format(pid=3013)]
        funding.scan(get=FakeGet(pages), now=NOW, sleep=lambda s: None)
        self.assertFalse(FundingCampaign.objects.filter(external_id='3013').exists())

    def test_unreadable_publisher_is_reported_and_retried(self):
        # 마크업이 바뀌어 '펴낸곳'류 라벨을 못 읽었지만, 본문에 한티재가 언급돼 있으면 우리 펀딩인지 알 수 없다 —
        # '우리 것 아님'으로 영구 기록하지 않고, 관리자에게 알려야 한다.
        pages = dict(PAGES, **{funding.ALADIN_VIEW_URL.format(pid=3013):
                               '<meta property="og:title" content="새 책" />한티재의 새 책입니다, 펴낸곳 표시가 없는 페이지'})
        result = funding.scan(get=FakeGet(pages), now=NOW, sleep=lambda s: None)
        self.assertFalse(FundingCampaign.objects.filter(external_id='3013').exists())
        self.assertEqual([c.platform for c in result.new], ['tumblbug'])
        self.assertIn('알라딘 북펀드: 펴낸곳을 읽지 못한 펀딩 1건', result.errors)

    def test_no_label_and_no_mention_is_recorded_not_ours_without_error(self):
        # 라벨도 없고 한티재 언급도 없으면 남의 펀딩이 거의 확실하다 — 매번 다시 열어보지 않도록 '아님'으로 기록한다.
        list_html = '<a href="/m/bookfund/view.aspx?pid=9001">x</a>'
        page = '<meta property="og:title" content="이벤트 공지" />별다른 정보 없음'
        get = FakeGet({funding.ALADIN_LIST_URL: list_html, funding.ALADIN_VIEW_URL.format(pid=9001): page})
        new, unreadable = funding._scan_aladin(get, NOW, lambda s: None)
        self.assertEqual((new, unreadable), ([], 0))
        camp = FundingCampaign.objects.get(external_id='9001')
        self.assertFalse(camp.is_ours)

    def test_no_label_but_mentions_publisher_is_unreadable(self):
        # 라벨은 없지만 한티재가 언급되면 우리 펀딩일 수 있다 — 기록하지 않고 다음 확인 때 다시 보며, 개수를 센다.
        list_html = '<a href="/m/bookfund/view.aspx?pid=9002">x</a>'
        page = '<meta property="og:title" content="신간" />한티재의 신간입니다, 펴낸곳 표시가 없는 페이지'
        get = FakeGet({funding.ALADIN_LIST_URL: list_html, funding.ALADIN_VIEW_URL.format(pid=9002): page})
        new, unreadable = funding._scan_aladin(get, NOW, lambda s: None)
        self.assertEqual((new, unreadable), ([], 1))
        self.assertFalse(FundingCampaign.objects.filter(external_id='9002').exists())

    def _tumblbug_page(self, projects):
        return json.dumps({'status': '200 OK', 'body': {'result': {'projects': projects}}}, ensure_ascii=False)

    def test_tumblbug_unparsable_end_date_is_not_recorded_and_counted(self):
        # 마감일을 못 읽으면 진행 중인지 알 수 없다 — 기록하지 않고 다음 확인 때 다시 보되, 개수는 센다.
        page = self._tumblbug_page([
            {'permalink': 'badend', 'title': '마감일이 깨진 프로젝트', 'fundingStartDate': '2026-09-20T10:00:00',
             'endDate': 'bad', 'isEnded': False},
            {'permalink': 'emptyend', 'title': '마감일이 없는 프로젝트', 'fundingStartDate': '2026-09-20T10:00:00',
             'endDate': '', 'isEnded': False},
            {'permalink': 'newbook', 'title': '새 책 펀딩', 'fundingStartDate': '2026-09-20T10:00:00',
             'endDate': '2026-10-20T23:59:59', 'isEnded': False},
        ])
        get = FakeGet({funding.TUMBLBUG_LIST_URL: page})
        new, unreadable = funding._scan_tumblbug(get, NOW)
        self.assertEqual(unreadable, 2)
        self.assertEqual([c.external_id for c in new], ['newbook'])
        self.assertFalse(FundingCampaign.objects.filter(external_id__in=['badend', 'emptyend']).exists())

    def test_scan_reports_tumblbug_unreadable_end_date(self):
        page = self._tumblbug_page([
            {'permalink': 'badend', 'title': '마감일이 깨진 프로젝트', 'fundingStartDate': '2026-09-20T10:00:00',
             'endDate': 'bad', 'isEnded': False},
        ])
        pages = dict(PAGES, **{funding.TUMBLBUG_LIST_URL: page})
        result = funding.scan(get=FakeGet(pages), now=NOW, sleep=lambda s: None)
        self.assertIn('텀블벅: 마감일을 읽지 못한 프로젝트 1건', result.errors)


@override_settings(INTAKE=CONFIG)
class FundBotTest(TestCase):
    def setUp(self):
        self.tg = FakeTG()
        TelegramChat.objects.create(chat_id=ADMIN, kind=TelegramChat.ADMIN)
        TelegramChat.objects.create(chat_id=GROUP, kind=TelegramChat.REVIEWERS)
        WorkerState.put('mode', 'live')

    def bot(self, pages=PAGES, broken=()):
        return Bot(self.tg, FakeLLM({}), config=CONFIG, fund_get=FakeGet(pages, broken))

    def test_new_fund_is_posted_and_announced(self):
        with mock.patch('intake.funding.time.sleep'):
            found = self.bot().run_fund_scan(NOW)
        self.assertEqual(len(found), 2)
        posted = Notice.objects.get(message='『농부, 짠한 형』 알라딘 북펀드 진행 중 · 10월 11일까지')
        self.assertEqual((posted.state, posted.link_label, posted.chat_id), (Notice.POSTED, '함께하기', GROUP))
        self.assertEqual(posted.ends_at, datetime(2026, 10, 12, 0, 0, tzinfo=KST))
        card = [c for c in self.tg.calls if c[0] == 'send' and c[1] == GROUP][0]
        self.assertIn('📣 새 북펀드를 찾아 사이트 첫 화면에 알림을 올렸어요', card[2])
        self.assertEqual(card[3]['inline_keyboard'][0][0]['callback_data'], f'ntoff:{posted.id}')

    def test_confirm_mode_creates_draft(self):
        WorkerState.put('fund_mode', 'confirm')
        with mock.patch('intake.funding.time.sleep'):
            self.bot().run_fund_scan(NOW)
        self.assertEqual(set(Notice.objects.values_list('state', flat=True)), {Notice.DRAFT})

    def test_errors_notify_admin_once_per_day(self):
        broken = set(PAGES)
        self.bot(broken=broken).run_fund_scan(NOW)
        self.bot(broken=broken).run_fund_scan(NOW + timedelta(hours=6))
        alerts = [c for c in self.tg.calls if c[0] == 'send' and c[1] == ADMIN and '북펀드 확인 실패' in c[2]]
        self.assertEqual(len(alerts), 1)

    def test_admin_fund_commands(self):
        bot = self.bot()
        bot.handle_update(msg(ADMIN, '/fund off', chat_type='private'))
        self.assertFalse(WorkerState.get('fund_autoscan'))
        bot.handle_update(msg(ADMIN, '/fund confirm', chat_type='private'))
        self.assertEqual(WorkerState.get('fund_mode'), 'confirm')
        FundingCampaign.objects.create(platform='aladin', external_id='3013', url='https://x', title='농부, 짠한 형',
                                       is_ours=True)
        bot.handle_update(msg(ADMIN, '/fund', chat_type='private'))
        self.assertIn('알라딘 북펀드 농부, 짠한 형', self.tg.texts()[-1])


@override_settings(INTAKE={'FUND_SCAN_SECONDS': 21600})
class FundPipelineTest(TestCase):
    def run_iteration(self, bot, now):
        tg = mock.Mock()
        tg.get_updates.return_value = []
        with mock.patch('intake.pipeline.run_pending'):
            pipeline.run_iteration(Deps(tg=tg, llm=None, bot=bot), now=now, sleep=lambda s: None)

    def test_fund_scan_runs_when_due_only(self):
        bot = mock.Mock()
        self.run_iteration(bot, NOW)
        self.run_iteration(bot, NOW + timedelta(hours=1))
        self.assertEqual(bot.run_fund_scan.call_count, 1)
        self.run_iteration(bot, NOW + timedelta(hours=7))
        self.assertEqual(bot.run_fund_scan.call_count, 2)
        WorkerState.put('fund_autoscan', False)
        self.run_iteration(bot, NOW + timedelta(hours=14))
        self.assertEqual(bot.run_fund_scan.call_count, 2)
