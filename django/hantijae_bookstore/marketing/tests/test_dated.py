from datetime import date, datetime, timedelta
from importlib import import_module, util

from django.test import TestCase

from context.models import ContextEntry
from intake.models import WorkerState
from marketing import candidates as C, moments as M, social_judge as J
from marketing.models import BookProfile, Proposal, Signal
from marketing.tests.fakes import FakeLLM, make_book, make_post
from marketing.timeutil import KST

TODAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 5, 30, tzinfo=KST)


class ExtractionTest(TestCase):
    def setUp(self):
        self.book = make_book()
        self.source = ContextEntry.objects.create(
            key='dated:1', at=NOW, text='오늘 한티재가 가을 북페어 부스를 엽니다. 책 2쇄를 찍었습니다.')

    def extract(self, **fields):
        raw = {'type': 'event', 'status': 'confirmed', 'title': '가을 북페어', 'date': TODAY.isoformat(),
               'summary': '한티재 부스', 'books': [self.book.title], 'evidence': [self.source.id], **fields}
        return M.run(FakeLLM({'new': [raw]}), NOW)

    def test_moment_onsite_accepts_only_boolean_true(self):
        for value in (True, False, 'true', 1, None):
            with self.subTest(value=value):
                Signal.objects.all().delete()
                report = self.extract(onsite=value)
                self.assertEqual(len(report.new), 1)
                self.assertIs(report.new[0].detail.get('onsite'), value is True)
                M.MomentScan.objects.all().delete()

    def test_reprint_keeps_only_exact_source_printing_and_short_value(self):
        for printing, wanted in (('2쇄', '2쇄'), ('3쇄', ''), ('2쇄' * 20, ''), (123, '')):
            with self.subTest(printing=printing):
                Signal.objects.all().delete()
                M.MomentScan.objects.all().delete()
                report = self.extract(type='reprint', title='책을 더 찍음', printing=printing)
                self.assertEqual(len(report.new), 1, report.dropped)
                self.assertEqual(report.new[0].detail.get('printing'), wanted)

    def test_update_changes_onsite_and_keeps_validated_printing(self):
        signal = Signal.objects.create(kind=Signal.MOMENT, key='old', title='가을 북페어', book=self.book,
                                       happens_on=TODAY, relevant=True,
                                       detail={'type': 'reprint', 'status': 'confirmed', 'onsite': True})
        report = M.run(FakeLLM({'updates': [{'id': signal.id, 'evidence': [self.source.id],
                                           'onsite': False, 'printing': '2쇄'}]}), NOW)
        self.assertTrue(report.changed)
        signal.refresh_from_db()
        self.assertIs(signal.detail.get('onsite'), False)
        self.assertEqual(signal.detail.get('printing'), '2쇄')

    def test_social_onsite_is_strict_and_survives_signal_storage(self):
        for value in (True, False, 'true', 1, None):
            with self.subTest(value=value):
                post = make_post(str(value) + str(type(value)), text='10월 14일 가을 북페어', posted_at=NOW)
                verdict = J.clean_verdict({'category': 'event', 'relevant': True,
                                          'event': {'date': TODAY.isoformat(), 'name': '가을 북페어',
                                                    'onsite': value}}, post, [])
                self.assertIs(verdict['event'].get('onsite'), value is True)
                signal = J.attach(post, verdict, NOW, {})
                self.assertIs(signal.detail['event'].get('onsite'), value is True)
                Signal.objects.all().delete()

    def test_later_social_evidence_can_correct_legacy_onsite(self):
        first = make_post('first', text='10월 14일 가을 북페어', posted_at=NOW)
        raw = {'category': 'event', 'relevant': True,
               'event': {'date': TODAY.isoformat(), 'name': '가을 북페어'}}
        old = J.attach(first, J.clean_verdict(raw, first, []), NOW, {})
        second = make_post('second', text='10월 14일 가을 북페어는 온라인 참석', posted_at=NOW)
        raw['event']['onsite'] = False
        newer = J.attach(second, J.clean_verdict(raw, second, []), NOW, {})
        self.assertEqual(old.pk, newer.pk)
        old.refresh_from_db()
        self.assertIs(old.detail['event'].get('onsite'), False)


class DatedTest(TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('marketing.dated'), '날짜 후보 모듈이 필요합니다')
        self.dated = import_module('marketing.dated')
        self.book = make_book()
        WorkerState.put('dated_mode', 'live')

    def signal(self, title, day=TODAY, source=Signal.MOMENT, book=None, **detail):
        if source == Signal.SOCIAL:
            base = {'category': 'event', 'event': {'on': day.isoformat() if day else '', 'name': title,
                                                  'place': '책방', 'onsite': True},
                    'books': [book.id] if book else []}
        else:
            base = {'type': 'event', 'status': 'confirmed', 'onsite': True,
                    'book_ids': [book.id] if book else []}
        s = Signal.objects.create(kind=source, key=f'{source}:{title}', title=title, book=book, happens_on=day,
                                  relevant=True, detail={**base, **detail})
        Signal.objects.filter(pk=s.pk).update(found_at=NOW)
        s.refresh_from_db()
        return s

    def test_three_kinds_have_distinct_keys_and_priority(self):
        today = self.signal('가을 북페어', book=self.book)
        after = self.signal('어제 북토크', TODAY - timedelta(days=1), book=self.book)
        reprint = self.signal('책을 더 찍음', None, book=self.book, type='reprint', onsite=False, printing='2쇄')
        self.assertEqual([(c.kind, c.id) for c in self.dated.items(TODAY, NOW)],
                         [('onsite_today', f'onsite:{today.id}:today'),
                          ('onsite_after', f'onsite:{after.id}:after'), ('reprint', f'reprint:{reprint.id}')])
        self.assertTrue(all(s.used_at is None for s in Signal.objects.all()))

    def test_off_does_nothing_but_preview_still_shows_upcoming_days_without_writes(self):
        self.signal('내일 축제', TODAY + timedelta(days=1))
        WorkerState.put('dated_mode', 'off')
        self.assertEqual(self.dated.items(TODAY, NOW), [])
        before = list(Signal.objects.values())
        preview = self.dated.preview(TODAY, NOW)
        self.assertIn('dated_mode=off', preview)
        self.assertIn('10/15', preview)
        self.assertIn('내일 축제', preview)
        self.assertIn('오늘 현장', preview)
        self.assertIn('어제 현장 후기', preview)
        self.assertEqual(list(Signal.objects.values()), before)
        self.assertEqual(Proposal.objects.count(), 0)

    def test_legacy_event_only_and_no_online_or_nonboolean_flag(self):
        legacy = self.signal('종이책 축제', onsite=True)
        legacy.detail.pop('onsite')
        legacy.save()
        author = self.signal('저자 혼자 강연', type='author')
        author.detail.pop('onsite')
        author.save()
        online = self.signal('온라인 축제')
        online.detail.pop('onsite')
        online.save()
        self.signal('문자 플래그', onsite='true')
        self.signal('숫자 플래그', onsite=1)
        self.signal('명시적 불참', onsite=False)
        live_author = self.signal('운영진 참석 강연', type='author')
        self.assertEqual([c.signal for c in self.dated.items(TODAY, NOW)], [legacy, live_author])

    def test_legacy_social_requires_event_category_and_valid_on_date(self):
        legacy = self.signal('축제 부스', source=Signal.SOCIAL,
                             event={'on': TODAY.isoformat(), 'name': '축제 부스', 'place': '광장'})
        self.signal('다른 소식', source=Signal.SOCIAL, category='author_news',
                    event={'on': TODAY.isoformat(), 'name': '저자 소식'})
        self.signal('온라인', source=Signal.SOCIAL,
                    event={'on': TODAY.isoformat(), 'name': '북토크', 'place': '온라인'})
        self.signal('날짜 모름', source=Signal.SOCIAL, event={'on': '틀린 날짜', 'onsite': True})
        self.assertEqual([c.signal for c in self.dated.items(TODAY, NOW)], [legacy])

    def test_quiet_cancelled_sensitive_and_promoted_after_are_excluded(self):
        self.signal('쉬는 책', book=self.book)
        BookProfile.objects.create(book=self.book, quiet_until=TODAY)
        self.signal('취소 행사', status='cancelled')
        secret = self.signal('민감 행사')
        Signal.objects.filter(pk=secret.pk).update(sensitive=True)
        self.signal('올린 후기', TODAY - timedelta(days=1), promoted=True)
        okay = self.signal('책 없는 행사')
        self.assertEqual([c.signal for c in self.dated.items(TODAY, NOW)], [okay])

    def test_quiet_secondary_books_do_not_leak_as_bookless(self):
        BookProfile.objects.create(book=self.book, quiet_until=TODAY)
        self.signal('대표 책 없는 SNS', source=Signal.SOCIAL, books=[self.book.id])
        self.signal('대표 책 없는 계기', book_ids=[self.book.id])
        self.assertEqual(self.dated.items(TODAY, NOW), [])

    def test_dedup_same_day_book_or_similar_name_prefers_moment(self):
        social = self.signal('출판사와 북토크', source=Signal.SOCIAL, book=self.book)
        moment = self.signal('북토크 현장', book=self.book)
        self.signal('가을 책 축제', source=Signal.SOCIAL)
        fair = self.signal('가을 책 축제 부스')
        other = self.signal('다른 날 북토크', TODAY - timedelta(days=1), book=self.book)
        result = self.dated.items(TODAY, NOW)
        self.assertEqual([c.signal for c in result], [moment, fair, other])
        self.assertIn(social, result[0].more_signals)

    def test_sent_duplicate_source_blocks_resend_but_preview_proposal_does_not(self):
        social = self.signal('북토크', source=Signal.SOCIAL, book=self.book)
        self.signal('북토크 현장', book=self.book)
        proposal = Proposal.objects.create(kind=Proposal.NOW, candidate_key=f'onsite:{social.id}:today', headline='x')
        self.assertEqual(len(self.dated.items(TODAY, NOW)), 1)
        proposal.sent_at = NOW
        proposal.save()
        self.assertEqual(self.dated.items(TODAY, NOW), [])

    def test_today_and_after_have_independent_sent_keys_even_if_signal_used(self):
        s = self.signal('북토크', book=self.book)
        Signal.objects.filter(pk=s.pk).update(used_at=NOW)
        self.assertEqual(len(self.dated.items(TODAY, NOW)), 1)
        Proposal.objects.create(kind=Proposal.NOW, candidate_key=f'onsite:{s.id}:today', headline='x', sent_at=NOW)
        tomorrow = TODAY + timedelta(days=1)
        self.assertEqual([c.id for c in self.dated.items(tomorrow, NOW + timedelta(days=1))],
                         [f'onsite:{s.id}:after'])

    def test_reprint_needs_book_recent_unused_and_unpromoted(self):
        fresh = self.signal('새 중쇄', None, book=self.book, type='reprint', onsite=False)
        self.signal('책 없는 중쇄', None, type='reprint', onsite=False)
        old = self.signal('오래된 중쇄', None, book=self.book, type='reprint', onsite=False)
        Signal.objects.filter(pk=old.pk).update(found_at=NOW - timedelta(days=15))
        used = self.signal('쓴 중쇄', None, book=self.book, type='reprint', onsite=False)
        Signal.objects.filter(pk=used.pk).update(used_at=NOW)
        self.signal('올린 중쇄', None, book=self.book, type='reprint', onsite=False, promoted=True)
        self.assertEqual([c.signal for c in self.dated.items(TODAY, NOW)], [fresh])

    def test_reprint_plan_or_future_print_date_cannot_be_announced_as_printed(self):
        self.signal('중쇄 계획', None, book=self.book, type='reprint', onsite=False, status='planned', printing='2쇄')
        self.signal('내일 중쇄', TODAY + timedelta(days=1), book=self.book, type='reprint', onsite=False,
                    printing='2쇄')
        self.assertEqual(self.dated.items(TODAY, NOW), [])

    def test_cancelled_moment_blocks_duplicate_social_event(self):
        self.signal('북토크 안내', source=Signal.SOCIAL, book=self.book)
        cancelled = self.signal('북토크 취소', book=self.book, status='cancelled')
        Signal.objects.filter(pk=cancelled.pk).update(relevant=False)
        self.assertEqual(self.dated.items(TODAY, NOW), [])

    def test_promoted_moment_blocks_duplicate_social_after(self):
        yesterday = TODAY - timedelta(days=1)
        self.signal('북토크 안내', yesterday, source=Signal.SOCIAL, book=self.book)
        self.signal('북토크 후기', yesterday, book=self.book, promoted=True)
        self.assertEqual(self.dated.items(TODAY, NOW), [])

    def test_fallback_today_only_has_facts_not_invented_experience(self):
        self.signal('가을 북페어')
        [candidate] = self.dated.items(TODAY, NOW)
        self.assertEqual(self.dated.fallback(candidate),
                         {'channel': 'instagram', 'title': '', 'body': '오늘 가을 북페어 현장입니다.\n#한티재의책'})
        candidate.kind = 'onsite_after'
        self.assertIsNone(self.dated.fallback(candidate))

    def test_monday_line_uses_today_events_and_is_gated(self):
        monday = date(2026, 10, 19)
        self.signal('책 축제', monday, place='시민회관')
        self.signal('지난 행사', monday - timedelta(days=1))
        text = self.dated.monday_line(monday, NOW + timedelta(days=5))
        self.assertIn('책 축제', text)
        self.assertIn('시민회관', text)
        self.assertIn('허락', text)
        self.assertNotIn('지난 행사', text)
        WorkerState.put('dated_mode', 'off')
        self.assertEqual(self.dated.monday_line(monday, NOW + timedelta(days=5)), '')

    def test_bookless_allowed_kinds_do_not_leak_all_quiet_candidates(self):
        BookProfile.objects.create(book=self.book, quiet_until=TODAY)
        candidates = [C.Candidate('quiet', 'onsite_today', [self.book], '쉬는 책', {}, 6),
                      C.Candidate('fair', 'onsite_today', [], '행사', {}, 6),
                      C.Candidate('editor', 'editor', [], '질문', {}, 4),
                      C.Candidate('reprint', 'reprint', [], '책 없음', {}, 3)]
        self.assertEqual([c.id for c in C.select(candidates, TODAY, NOW)], ['fair', 'editor'])
        self.assertEqual(candidates[1].as_prompt()['kind'], '오늘 현장')
