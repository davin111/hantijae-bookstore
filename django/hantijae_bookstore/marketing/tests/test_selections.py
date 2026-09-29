import json
from datetime import date, datetime, timedelta
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from intake.models import WorkerState
from marketing.models import BookProfile, SelectionAnnouncement, Signal
from marketing.selection_sources import Announcement
from marketing.selections import Found, announce, collect, notice_message, run_scan, _track_failures
from marketing.tests.fakes import FakeTG, make_book
from marketing.timeutil import KST
from web.models import Notice

TODAY = date(2026, 9, 30)


def ann(key='kpipa:2145', texts=('1 9791192455808',), fresh=True, withdrawal=False, label='2026년 세종도서 교양부문'):
    return Announcement('kpipa', key, label, 'https://www.kpipa.or.kr/p/g1_2/2145', date(2026, 8, 25), fresh,
                        list(texts), withdrawal)


def boom(*_):
    raise ValueError('page changed')


class CollectTest(TestCase):
    def setUp(self):
        self.book = make_book(title='무궁화호를 위하여', published=date(2026, 3, 16),
                              isbn='979-11-92455-80-8  03300', author='하승우')

    def run_with(self, *scanners):
        with mock.patch('marketing.selections.SCANNERS', list(scanners)):
            return collect(TODAY, get_text=None, get_bytes=None, sleep=lambda _: None)

    def test_records_announcement_and_signal_for_isbn_hit(self):
        found, failed = self.run_with(('kpipa', '출판진흥원 결과공고', lambda *a: [ann()]))
        self.assertEqual(failed, [])
        self.assertEqual([(f.how, f.signal.book) for f in found], [('isbn', self.book)])
        s = found[0].signal
        self.assertEqual((s.kind, s.key, s.title, s.happens_on, s.relevant),
                         (Signal.SELECTION, f'selection:kpipa:2145:{self.book.id}', '2026년 세종도서 교양부문',
                          date(2026, 8, 25), True))
        self.assertEqual(s.detail, {'source': 'kpipa', 'match': 'isbn', 'withdrawal': False, 'fresh': True})
        self.assertEqual(SelectionAnnouncement.objects.get().matched, 1)

    def test_announcement_without_hits_is_still_remembered(self):
        self.run_with(('kpipa', 'x', lambda *a: [ann(texts=['다른 책 9790000000000'])]))
        self.assertEqual((SelectionAnnouncement.objects.get().matched, Signal.objects.count()), (0, 0))

    def test_seen_keys_are_passed_to_scanners(self):
        SelectionAnnouncement.objects.create(key='kpipa:2145', source='kpipa', label='x', url='https://x.kr')
        box = []
        self.run_with(('kpipa', 'x', lambda today, seen, *a: box.append(set(seen)) or []))
        self.assertEqual(box, [{'kpipa:2145'}])

    def test_old_announcement_signal_is_not_relevant(self):
        found, _ = self.run_with(('kpipa', 'x', lambda *a: [ann(fresh=False)]))
        self.assertFalse(found[0].signal.relevant)

    def test_withdrawal_signal_is_not_relevant(self):
        found, _ = self.run_with(('kpipa', 'x', lambda *a: [ann(withdrawal=True)]))
        self.assertFalse(found[0].signal.relevant)
        self.assertTrue(SelectionAnnouncement.objects.get().withdrawal)

    def test_one_failing_source_is_reported_others_continue(self):
        found, failed = self.run_with(('tkpf', '청소년 교양도서', boom), ('kpipa', 'x', lambda *a: [ann()]))
        self.assertEqual((failed, len(found)), (['tkpf'], 1))

    def test_all_sources_failing_raises(self):
        with self.assertRaises(RuntimeError):
            self.run_with(('kpipa', '출판진흥원', boom), ('nl', '국립중앙도서관', boom))

    def test_duplicate_key_in_same_run_is_skipped(self):
        found, failed = self.run_with(('kpipa', 'x', lambda *a: [ann(), ann()]))
        self.assertEqual(failed, [])
        self.assertEqual(len(found), 1)
        self.assertEqual(SelectionAnnouncement.objects.count(), 1)


NOW = datetime(2026, 9, 30, 6, 10, tzinfo=KST)


class FakeMarketing:
    def __init__(self, mode, chat):
        self._mode, self._chat = mode, chat

    def mode(self):
        return self._mode

    def target_chat(self):
        return self._chat


def make_deps(mode='live', chat=-100):
    notes = []
    bot = SimpleNamespace(tg=FakeTG(), marketing=FakeMarketing(mode, chat), notes=notes, notify_admin=notes.append)
    return SimpleNamespace(bot=bot)


class AnnounceTest(TestCase):
    def setUp(self):
        self.book = make_book(title='무궁화호를 위하여', published=date(2026, 3, 16),
                              isbn='979-11-92455-80-8  03300', author='하승우')

    def found(self, how='isbn', **kw):
        a = ann(**kw)
        sig = Signal.objects.create(kind=Signal.SELECTION, key=f'selection:{a.key}:{self.book.id}', book=self.book,
                                    title=a.label, url=a.url, detail={'match': how}, relevant=True)
        return Found(sig, how, a)

    def test_isbn_hit_in_live_mode_posts_notice_and_sends_card(self):
        deps = make_deps()
        notice = announce(deps, self.found(), NOW)
        self.assertEqual((notice.state, notice.message, notice.link_label, notice.created_by),
                         (Notice.POSTED, '『무궁화호를 위하여』 2026년 세종도서 교양부문 선정', '책 보기', '공공 선정 자동 감지'))
        self.assertTrue(notice.link_url.endswith(f'/book={self.book.id}'))
        self.assertEqual(notice.ends_at, NOW + timedelta(days=30))
        card = deps.bot.tg.sent('send')[0]
        self.assertEqual(card['chat'], -100)
        self.assertIn('사이트 첫 화면에 알림을 올렸어요', card['text'])
        self.assertIn('ntoff:', json.dumps(card['buttons']))
        notice.refresh_from_db()
        self.assertEqual((notice.chat_id, notice.message_id), (-100, 1001))
        self.assertTrue(Signal.objects.get().detail['posted'])

    def test_quiet_book_is_not_auto_posted_even_on_isbn_hit(self):
        BookProfile.objects.create(book=self.book, quiet_until=date(2026, 10, 15))
        deps = make_deps()
        notice = announce(deps, self.found(), NOW)
        self.assertEqual(notice.state, Notice.DRAFT)
        card = deps.bot.tg.sent('send')[0]
        self.assertIn('홍보를 쉬는 중', card['text'])
        self.assertIn('ntpub:', json.dumps(card['buttons']))

    def test_title_hit_makes_draft_card_not_posted(self):
        deps = make_deps()
        notice = announce(deps, self.found(how='title'), NOW)
        self.assertEqual(notice.state, Notice.DRAFT)
        card = deps.bot.tg.sent('send')[0]
        self.assertIn('제목으로 찾았어요', card['text'])
        self.assertIn('ntpub:', json.dumps(card['buttons']))

    def test_admin_only_mode_never_posts(self):
        self.assertEqual(announce(make_deps(mode='admin_only', chat=7), self.found(), NOW).state, Notice.DRAFT)

    def test_no_chat_still_creates_notice_without_card(self):
        deps = make_deps(chat=None)
        announce(deps, self.found(), NOW)
        self.assertEqual(deps.bot.tg.sent(), [])

    def test_notice_message_clips_long_title(self):
        msg = notice_message('아주 긴 제목 ' * 10, '2026년 세종도서 교양부문')
        self.assertLessEqual(len(msg), 60)
        self.assertTrue(msg.endswith('』 2026년 세종도서 교양부문 선정'))
        self.assertIn('…』', msg)

    def test_run_scan_skips_old_and_alerts_withdrawal(self):
        deps = make_deps()
        fresh, old = self.found(key='kpipa:1'), self.found(key='kpipa:2', fresh=False)
        gone = self.found(key='kpipa:3', withdrawal=True, label='2026년 문학나눔')
        with mock.patch('marketing.selections.collect', return_value=([fresh, old, gone], [])):
            run_scan(deps, TODAY, NOW)
        self.assertEqual(Notice.objects.count(), 1)
        self.assertEqual(len(deps.bot.notes), 1)
        self.assertIn('2026년 문학나눔', deps.bot.notes[0])
        self.assertIn('『무궁화호를 위하여』', deps.bot.notes[0])

    def test_failure_streak_alerts_once_on_third_day(self):
        deps = make_deps()
        for _ in range(4):
            _track_failures(deps, ['nl'])
        self.assertEqual(len([n for n in deps.bot.notes if '국립중앙도서관' in n and '3일째' in n]), 1)
        _track_failures(deps, [])
        self.assertEqual(WorkerState.get('selection_fail_nl'), 0)

    def test_announce_failure_sends_one_card_and_alerts_on_other(self):
        deps = make_deps()
        fresh1 = self.found(key='kpipa:1')
        fresh2 = self.found(key='kpipa:2', label='2026년 문학나눔')
        call_count = [0]
        original_send = deps.bot.tg.send_message

        def failing_send(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError('Telegram down')
            return original_send(*args, **kwargs)

        deps.bot.tg.send_message = failing_send
        with mock.patch('marketing.selections.collect', return_value=([fresh1, fresh2], [])):
            with self.assertLogs('intake', level='WARNING') as logs:
                run_scan(deps, TODAY, NOW)
        self.assertEqual(Notice.objects.count(), 2)
        self.assertEqual(len(deps.bot.tg.sent('send')), 1)
        admin_notes = [n for n in deps.bot.notes if '알림을 보내지 못했어요' in n and '무궁화호를 위하여' in n]
        self.assertEqual(len(admin_notes), 1)

    def test_run_scan_survives_fully_down_telegram(self):
        deps = make_deps()
        fresh1 = self.found(key='kpipa:1')
        fresh2 = self.found(key='kpipa:2', label='2026년 문학나눔')
        deps.bot.tg.send_message = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Telegram down'))
        deps.bot.notify_admin = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Telegram down'))
        with mock.patch('marketing.selections.collect', return_value=([fresh1, fresh2], [])):
            with self.assertLogs('intake', level='WARNING') as logs:
                run_scan(deps, TODAY, NOW)
        self.assertEqual(Notice.objects.count(), 2)

    def test_one_notice_per_book_even_when_the_same_selection_is_listed_twice(self):
        """같은 책이 같은 발표에 두 번 걸려도(목록 엔트리가 겹치는 등) 알림 띠는 한 번만 만든다."""
        deps = make_deps()
        fresh1, fresh2 = self.found(key='kpipa:1'), self.found(key='kpipa:2')
        with mock.patch('marketing.selections.collect', return_value=([fresh1, fresh2], [])):
            run_scan(deps, TODAY, NOW)
        self.assertEqual(Notice.objects.count(), 1)
        self.assertEqual(len(deps.bot.tg.sent('send')), 1)


class CommandTest(TestCase):
    def test_dry_run_reports_but_keeps_nothing(self):
        make_book(title='무궁화호를 위하여', published=date(2026, 3, 16), isbn='979-11-92455-80-8  03300', author='하승우')
        out = StringIO()
        with mock.patch('marketing.selections.SCANNERS', [('kpipa', '출판진흥원 결과공고', lambda *a: [ann()])]):
            call_command('marketing_scan_selections', '--dry-run', stdout=out)
        self.assertIn('찾은 책 1건', out.getvalue())
        self.assertIn('『무궁화호를 위하여』', out.getvalue())
        self.assertEqual((SelectionAnnouncement.objects.count(), Signal.objects.count()), (0, 0))
