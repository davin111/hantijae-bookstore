from datetime import date, datetime, timedelta

from django.test import TestCase

from intake.models import WorkerState
from marketing.models import BookProfile, Draft, HookDate, Proposal, Signal
from marketing.tests.fakes import make_book
from marketing.timeutil import KST


DAY = date(2026, 10, 9)
NOW = datetime(2026, 10, 9, 5, 30, tzinfo=KST)


class SeriesCandidatesTest(TestCase):
    def setUp(self):
        WorkerState.put('series_mode', 'live')
        self.book = make_book(published=date(2025, 1, 1))

    def signal(self, key='news:a', kind=Signal.NEWS, book=None, on=None, found=None, **kwargs):
        s = Signal.objects.create(kind=kind, key=key, book=book or self.book, relevant=True,
                                  title=kwargs.pop('title', '저자 인터뷰'),
                                  detail=kwargs.pop('detail', {'summary': '저자가 책 이야기를 나누었습니다.'}),
                                  url=kwargs.pop('url', 'https://example.test/news/a'),
                                  happens_on=on or DAY - timedelta(days=1), **kwargs)
        Signal.objects.filter(pk=s.pk).update(found_at=found or NOW - timedelta(days=1))
        s.refresh_from_db()
        return s

    def items(self, day=DAY):
        from marketing.series import items
        return items(day, datetime.combine(day, NOW.timetz()))

    def weekly(self, day=DAY):
        return [c for c in self.items(day) if c.kind == 'series_week']

    def test_off_and_non_friday_do_not_generate_or_mark_an_attempt(self):
        self.signal()
        WorkerState.put('series_mode', 'off')
        self.assertEqual(self.items(), [])
        self.assertIsNone(WorkerState.get('series_state'))
        WorkerState.put('series_mode', 'live')
        self.assertEqual(self.items(DAY - timedelta(days=1)), [])
        self.assertIsNone(WorkerState.get('series_state'))

    def test_empty_week_does_not_make_up_a_roundup(self):
        self.assertEqual(self.items(), [])
        state = WorkerState.get('series_state')
        self.assertEqual(state['status'], 'no_news')
        self.assertEqual(state['candidate_keys'], [])
        self.assertNotIn('sent_at', state)

    def test_single_story_is_standalone_and_two_distinct_stories_are_roundup(self):
        a = self.signal()
        c = self.weekly()[0]
        self.assertEqual(c.id, 'series:week:2026-10-05')
        self.assertEqual(c.facts['series_form'], 'standalone')
        self.assertEqual(c.facts['expected_channel'], 'blog')
        self.assertEqual(c.facts['source_urls'], [a.url])
        self.assertIn('저자 인터뷰', c.summary)
        self.signal('selection:b', kind=Signal.SELECTION, title='공공 도서 선정', url='https://example.test/selection/b')
        c = self.weekly()[0]
        self.assertEqual(c.facts['series_form'], 'roundup')
        self.assertEqual(len(c.facts['stories']), 2)
        self.assertEqual(WorkerState.get('series_state')['status'], 'generated')
        self.assertEqual(Signal.objects.filter(used_at__isnull=False).count(), 0)

    def test_duplicate_linked_event_counts_once_and_keeps_both_signal_ids(self):
        a = self.signal()
        b = self.signal('moment:a', kind=Signal.MOMENT, title='같은 저자 인터뷰',
                        detail={'type': 'author', 'status': 'done', 'summary': '같은 인터뷰 소식'},
                        url=a.url + '?utm_source=telegram')
        c = self.weekly()[0]
        self.assertEqual(c.facts['series_form'], 'standalone')
        self.assertEqual(len(c.facts['stories']), 1)
        self.assertEqual({c.signal.pk, *[s.pk for s in c.more_signals]}, {a.pk, b.pk})

    def test_sensitive_cancelled_promoted_or_hidden_books_are_not_recycled(self):
        for kwargs in ({'sensitive': True}, {'detail': {'status': 'cancelled'}}, {'detail': {'promoted': True}}):
            with self.subTest(kwargs=kwargs):
                s = self.signal(**kwargs)
                self.assertEqual(self.weekly(), [])
                s.delete()
        self.book.visible = False
        self.book.save(update_fields=['visible'])
        self.signal()
        self.assertEqual(self.weekly(), [])

    def test_quiet_book_in_multi_book_story_blocks_whole_story(self):
        second = make_book(title='다른 책', isbn='979-11-00000-19-9', author=None)
        BookProfile.objects.create(book=second, quiet_until=DAY)
        self.signal(kind=Signal.MOMENT, detail={'type': 'event', 'status': 'done',
                                               'summary': '두 책을 함께 소개했습니다.',
                                               'book_ids': [self.book.pk, second.pk]})
        self.assertEqual(self.weekly(), [])

    def test_previously_posted_or_placed_signal_is_not_proposed_again(self):
        s = self.signal()
        p = Proposal.objects.create(kind=Proposal.NOW, headline='지난 소식', signal=s)
        d = Draft.objects.create(proposal=p, channel=Draft.BLOG, body='글', status=Draft.POSTED)
        self.assertEqual(self.weekly(), [])
        d.status = Draft.DRAFT
        d.placements = [{'url': 'https://blog.test/already'}]
        d.save(update_fields=['status', 'placements'])
        self.assertEqual(self.weekly(), [])

    def test_posted_duplicate_and_cancelled_duplicate_cannot_return_under_another_source(self):
        a = self.signal()
        self.signal('news:copy', title='같은 기사', url=a.url + '?utm_medium=social')
        a.sensitive = True
        a.save(update_fields=['sensitive'])
        self.assertEqual(self.weekly(), [])

    def test_old_future_and_unconfirmed_moments_are_not_last_week_news(self):
        cases = [{'found': NOW - timedelta(days=8), 'on': DAY - timedelta(days=8)},
                 {'on': DAY + timedelta(days=1)},
                 {'kind': Signal.MOMENT, 'detail': {'type': 'event', 'status': 'planned', 'summary': '검토 중'}}]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                s = self.signal(**kwargs)
                self.assertEqual(self.weekly(), [])
                s.delete()

    def test_collector_error_is_not_reported_as_no_news(self):
        WorkerState.put('marketing_error_news', DAY.isoformat())
        self.assertEqual(self.items(), [])
        self.assertEqual(WorkerState.get('series_state')['status'], 'source_failed')

    def test_actual_selection_and_moment_guard_failures_are_not_silence(self):
        for name in ('selection', 'moment'):
            WorkerState.put(f'marketing_error_{name}', DAY.isoformat())
            self.assertEqual(self.items(), [])
            self.assertIn(name, WorkerState.get('series_state')['source_errors'])

    def test_posted_multi_signal_proposal_excludes_every_linked_story(self):
        a = self.signal()
        b = self.signal('news:b', title='다른 소식', url='https://example.test/b')
        p = Proposal.objects.create(kind=Proposal.NOW, headline='모음', signal=a,
                                    extra={'more_signal_ids': [b.pk]})
        Draft.objects.create(proposal=p, channel=Draft.BLOG, body='글', status=Draft.POSTED)
        self.assertEqual(self.weekly(), [])

    def test_unknown_date_or_unverified_date_is_not_presented_as_confirmed_event(self):
        self.signal(kind=Signal.MOMENT, detail={'type': 'event', 'status': 'confirmed',
                                               'summary': '날짜를 아직 확인하지 못함', 'date_unverified': True})
        self.assertEqual(self.weekly(), [])

    def test_reread_does_not_recommend_memorial_as_a_sales_opportunity(self):
        h = HookDate.objects.create(name='추모일', month=10, day=10, memorial=True)
        h.books.add(self.book)
        row = [c for c in self.items() if c.kind == 'series_reread'][0]
        self.assertTrue(row.memorial)

    def test_sent_week_is_not_generated_again_but_preview_is_not_sent(self):
        self.signal()
        p = Proposal.objects.create(kind=Proposal.NOW, candidate_key='series:week:2026-10-05',
                                    headline='미리보기', status=Proposal.PROPOSED)
        self.assertEqual(len(self.weekly()), 1)
        p.sent_at, p.status = NOW, Proposal.SHOWN
        p.save(update_fields=['sent_at', 'status'])
        self.assertEqual(self.weekly(), [])

    def test_reread_needs_verified_hook_and_uses_every_other_friday(self):
        self.assertEqual([c for c in self.items() if c.kind == 'series_reread'], [])
        h = HookDate.objects.create(name='세계 식량의 날', month=10, day=16,
                                     source_url='https://example.test/calendar/food')
        h.books.add(self.book)
        rows = [c for c in self.items() if c.kind == 'series_reread']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].id, 'series:reread:2026-10-05')
        self.assertEqual(rows[0].facts['expected_channel'], 'blog')
        self.assertIn(h.source_url, rows[0].facts['source_urls'])
        self.assertEqual([c for c in self.items(date(2026, 10, 16)) if c.kind == 'series_reread'], [])

    def test_reread_excludes_new_books_and_recently_proposed_books(self):
        h = HookDate.objects.create(name='기념일', month=10, day=10)
        h.books.add(self.book)
        p = Proposal.objects.create(kind=Proposal.NOW, candidate_key='old', headline='이전에 제안', book=self.book)
        Proposal.objects.filter(pk=p.pk).update(created_at=NOW - timedelta(days=20))
        self.assertEqual([c for c in self.items() if c.kind == 'series_reread'], [])
        p.delete()
        self.book.published_date = DAY - timedelta(days=179)
        self.book.save(update_fields=['published_date'])
        self.assertEqual([c for c in self.items() if c.kind == 'series_reread'], [])

    def test_reread_can_use_actual_author_news_when_roundup_is_already_sent(self):
        self.signal()
        Proposal.objects.create(kind=Proposal.NOW, candidate_key='series:week:2026-10-05',
                                headline='주간 소식', sent_at=NOW, status=Proposal.SHOWN)
        rows = [c for c in self.items() if c.kind == 'series_reread']
        self.assertEqual(len(rows), 1)
        self.assertIn('저자 인터뷰', rows[0].summary)

    def proposal(self, candidate):
        return Proposal.objects.create(
            kind=Proposal.NOW, candidate_key=candidate.id, headline=candidate.summary[:300],
            book=candidate.books[0] if candidate.books else None, signal=candidate.signal,
            extra={'book_ids': [b.pk for b in candidate.books],
                   'more_signal_ids': [s.pk for s in candidate.more_signals]})

    def can_send(self, proposal, today=DAY):
        from marketing import series
        self.assertTrue(callable(getattr(series, 'can_send', None)), '연재 발송 전 현재 근거 재검사가 필요합니다')
        return series.can_send(proposal, today, datetime.combine(today, NOW.timetz()))

    def test_pending_weekly_stays_sendable_without_rewriting_generation_state(self):
        self.signal()
        p = self.proposal(self.weekly()[0])
        state = WorkerState.get('series_state')
        self.assertTrue(self.can_send(p))
        self.assertEqual(WorkerState.get('series_state'), state)

    def test_actual_post_or_placement_during_wait_blocks_series_send(self):
        signal = self.signal()
        p = self.proposal(self.weekly()[0])
        earlier = Proposal.objects.create(kind=Proposal.NOW, signal=signal, headline='이미 올린 글')
        d = Draft.objects.create(proposal=earlier, channel=Draft.BLOG, body='같은 소식', status=Draft.POSTED)
        self.assertFalse(self.can_send(p))
        d.status, d.placements = Draft.DRAFT, [{'url': 'https://blog.test/already'}]
        d.save(update_fields=['status', 'placements'])
        self.assertFalse(self.can_send(p))

    def test_new_cancelled_duplicate_during_wait_blocks_existing_series(self):
        signal = self.signal()
        p = self.proposal(self.weekly()[0])
        self.signal('moment:cancel', kind=Signal.MOMENT, title='취소된 안내',
                    detail={'type': 'event', 'status': 'cancelled'}, url=signal.url + '?utm_source=room')
        self.assertFalse(self.can_send(p))

    def test_promoted_source_or_removed_story_blocks_entire_saved_roundup(self):
        first = self.signal()
        second = self.signal('news:b', title='두 번째 소식', url='https://example.test/b')
        p = self.proposal(self.weekly()[0])
        first.detail = {'promoted': True}
        first.save(update_fields=['detail'])
        self.assertFalse(self.can_send(p))
        first.detail = {'summary': '저자 인터뷰'}
        first.save(update_fields=['detail'])
        second.delete()
        self.assertFalse(self.can_send(p))

    def test_quiet_secondary_book_during_wait_blocks_whole_series(self):
        self.signal()
        second = make_book(title='둘째 책', isbn='979-11-00000-29-9', author=None)
        self.signal('news:b', book=second, title='둘째 소식', url='https://example.test/b')
        p = self.proposal(self.weekly()[0])
        BookProfile.objects.create(book=second, quiet_until=DAY)
        self.assertFalse(self.can_send(p))

    def test_reread_ignores_its_own_generated_row_and_admin_preview(self):
        hook = HookDate.objects.create(name='기념일', month=10, day=10)
        hook.books.add(self.book)
        p = self.proposal([c for c in self.items() if c.kind == 'series_reread'][0])
        self.assertTrue(self.can_send(p))
        p.sent_at, p.status = NOW, Proposal.SHOWN
        p.extra['content_preview_at'] = NOW.isoformat()
        p.save(update_fields=['sent_at', 'status', 'extra'])
        self.assertTrue(self.can_send(p))
        hook.books.clear()
        self.assertFalse(self.can_send(p))

    def test_another_recent_proposal_still_blocks_reread_send(self):
        hook = HookDate.objects.create(name='기념일', month=10, day=10)
        hook.books.add(self.book)
        p = self.proposal([c for c in self.items() if c.kind == 'series_reread'][0])
        Proposal.objects.create(kind=Proposal.NOW, book=self.book, headline='다른 제안')
        self.assertFalse(self.can_send(p))

    def test_mode_week_and_room_success_are_rechecked_before_send(self):
        self.signal()
        p = self.proposal(self.weekly()[0])
        self.assertFalse(self.can_send(p, DAY + timedelta(days=1)))
        self.assertFalse(self.can_send(p, DAY + timedelta(days=7)))
        WorkerState.put('series_mode', 'off')
        self.assertFalse(self.can_send(p))
        WorkerState.put('series_mode', 'live')
        p.extra['content_room_sent_at'] = NOW.isoformat()
        p.save(update_fields=['extra'])
        self.assertFalse(self.can_send(p))

    def test_partial_selection_failure_is_not_no_news_until_source_recovers(self):
        WorkerState.put('marketing_last_selection_scan', '2026-10-08')
        WorkerState.put('selection_fail_nl', 2)
        self.assertEqual(self.items(), [])
        self.assertEqual(WorkerState.get('series_state')['status'], 'source_failed')
        self.assertIn('selection', WorkerState.get('series_state')['source_errors'])
        WorkerState.put('selection_fail_nl', 0)
        self.assertEqual(self.items(), [])
        self.assertEqual(WorkerState.get('series_state')['status'], 'no_news')

    def test_latest_selection_attempt_failure_survives_before_next_scan(self):
        WorkerState.put('marketing_last_selection_scan', '2026-10-08')
        WorkerState.put('marketing_error_selection', '2026-10-08')
        self.assertEqual(self.items(), [])
        self.assertEqual(WorkerState.get('series_state')['status'], 'source_failed')
        WorkerState.put('marketing_last_selection_scan', '2026-10-09')
        self.assertEqual(self.items(), [])
        self.assertEqual(WorkerState.get('series_state')['status'], 'no_news')
