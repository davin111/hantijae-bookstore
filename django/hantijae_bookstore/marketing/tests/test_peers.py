from datetime import date, datetime, timedelta
from importlib import import_module, util
import json

from django.test import TestCase

from intake.models import WorkerState
from marketing.meta import Media
from marketing.models import Proposal, Signal
from marketing.tests.fakes import FakeLLM
from marketing.timeutil import KST

TODAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 4, 55, tzinfo=KST)


def media(identifier='1', caption='작은 출판사의 편집 이야기를 전합니다.', age=1, likes=10, comments=1):
    return Media(identifier, caption, f'https://www.instagram.com/p/{identifier}/', NOW - timedelta(days=age),
                 likes=likes, comments=comments)


def verdict(identifier=0, **fields):
    return {'id': identifier, 'summary': '편집실에서 생긴 일을 짧은 글로 소개했다.', 'type': 'editorial',
            'sensitive': False, 'cancelled': False, 'event': None, **fields}


class PeerTest(TestCase):
    def setUp(self):
        self.assertIsNotNone(util.find_spec('marketing.peers'), '참고 출판사 수집 모듈이 필요합니다')
        self.peers = import_module('marketing.peers')
        self.source = self.peers.Source('ig', 'testpress', '참고 출판사')
        WorkerState.put('peer_mode', 'live')

    def run_ig(self, rows, reply=None, now=NOW, sources=None):
        return self.peers.run(FakeLLM(reply or {'items': [verdict()]}), now.date(), now,
                              sources=sources or [self.source], business_media=lambda *a, **kw: rows)

    def test_mode_off_prevents_all_reads_and_writes(self):
        WorkerState.put('peer_mode', 'off')
        def forbidden(*args, **kwargs):
            self.fail('꺼진 수집기가 네트워크를 읽었습니다')
        report = self.peers.run(FakeLLM([]), TODAY, NOW, sources=[self.source], business_media=forbidden)
        self.assertEqual((report.checked, report.new, report.failures), (0, [], {}))
        self.assertIsNone(WorkerState.get('peer_scan_state'))

    def test_short_summary_only_and_duplicate_refreshes_counts_without_llm(self):
        caption = '원문 보관 금지 표시. ' + '출판사의 작업을 소개하는 긴 원문입니다. ' * 30
        result = self.run_ig([media(caption=caption)])
        self.assertEqual(len(result.new), 1)
        signal = Signal.objects.get()
        self.assertEqual(signal.key, 'peer:ig:1')
        self.assertEqual(signal.kind, 'peer')
        self.assertNotIn('원문 보관 금지 표시', json.dumps(signal.detail, ensure_ascii=False))
        self.assertEqual(signal.detail['likes'], 10)
        again = self.peers.run(FakeLLM([]), TODAY, NOW + timedelta(minutes=1), sources=[self.source],
                               business_media=lambda *a, **kw: [media(caption=caption, likes=22)])
        signal.refresh_from_db()
        self.assertEqual((again.new, signal.detail['likes'], Signal.objects.count()), ([], 22, 1))

    def test_none_is_failure_empty_is_success_and_failed_watermark_is_preserved(self):
        self.run_ig([])
        before = WorkerState.get('peer_scan_state')['sources']['ig:testpress']['success_at']
        result = self.run_ig(None, now=NOW + timedelta(days=1))
        state = WorkerState.get('peer_scan_state')['sources']['ig:testpress']
        self.assertIn('ig:testpress', result.failures)
        self.assertEqual(state['success_at'], before)
        self.assertEqual(state['failure_count'], 1)
        self.run_ig([], now=NOW + timedelta(days=2))
        state = WorkerState.get('peer_scan_state')['sources']['ig:testpress']
        self.assertEqual(state['failure_count'], 0)
        self.assertNotEqual(state['success_at'], before)

    def test_one_account_failure_does_not_hide_other_success_or_leak_error_url(self):
        second = self.peers.Source('ig', 'otherpress', '다른 출판사')
        def fetch(account, **kw):
            if account == 'testpress':
                raise RuntimeError('https://example.test?access_token=PRIVATE')
            return [media()]
        result = self.peers.run(FakeLLM({'items': [verdict()]}), TODAY, NOW,
                                sources=[self.source, second], business_media=fetch)
        self.assertEqual(len(result.new), 1)
        self.assertEqual(list(result.failures), ['ig:testpress'])
        self.assertNotIn('PRIVATE', json.dumps(WorkerState.get('peer_scan_state')))

    def test_batch_limit_and_omission_leave_posts_for_retry(self):
        rows = [media(str(i), age=i + 1) for i in range(8)]
        llm = FakeLLM({'items': [verdict(0)]})
        result = self.peers.run(llm, TODAY, NOW, sources=[self.source], business_media=lambda *a, **kw: rows)
        self.assertEqual(len(llm.calls), 1)
        sent = json.loads(llm.calls[0][1])
        self.assertEqual(len(sent['posts']), 5)
        self.assertEqual(len(result.new), 1)
        self.assertIn('ig:testpress', result.failures)
        state = WorkerState.get('peer_scan_state')['sources']['ig:testpress']
        self.assertFalse(state.get('success_at'))
        self.assertEqual(state['backlog'], 7)
        retried = self.run_ig(rows, {'items': [verdict(i) for i in range(5)]})
        self.assertEqual(len(retried.new), 5)

    def test_old_posts_only_build_bounded_count_baseline(self):
        rows = [media(str(i), age=i + 15) for i in range(100)]
        result = self.peers.run(FakeLLM([]), TODAY, NOW, sources=[self.source],
                                business_media=lambda *a, **kw: rows)
        self.assertEqual(result.new, [])
        state = WorkerState.get('peer_scan_state')['sources']['ig:testpress']
        self.assertLessEqual(len(state['baseline']), 100)
        self.assertEqual(max(p['posted_on'] for p in state['baseline']), '2026-09-29')
        self.assertNotIn('caption', json.dumps(state))

    def test_future_opportunity_requires_verified_date_and_source_invitation(self):
        caption = '10월 20일 가을 북페어. 광장에서 출판사 부스 참가를 모집합니다.'
        event = {'date': '2026-10-20', 'name': '가을 북페어', 'place': '광장',
                 'opportunity': '출판사 부스 참가를 검토할 수 있음', 'public': True, 'collaboration': True,
                 'evidence': '출판사 부스 참가를 모집합니다'}
        self.run_ig([media(caption=caption)], {'items': [verdict(type='event', event=event)]})
        [candidate] = self.peers.candidate_items(TODAY, NOW)
        self.assertEqual((candidate.kind, candidate.books, candidate.facts['date']),
                         ('peer_event', [], '2026-10-20'))
        self.assertIn('검토', candidate.summary)
        self.assertNotIn('한티재가 참석', candidate.summary)
        Proposal.objects.create(kind=Proposal.NOW, candidate_key=candidate.id, headline='x', sent_at=NOW)
        self.assertEqual(self.peers.candidate_items(TODAY, NOW), [])

    def test_unsupported_event_date_or_invitation_never_becomes_candidate(self):
        for event in ({'date': '2026-10-20', 'name': '북페어', 'place': '', 'opportunity': '부스 참여',
                       'public': True, 'collaboration': True, 'evidence': '참가를 모집합니다'},
                      {'date': '2026-10-20', 'name': '북페어', 'place': '', 'opportunity': '부스 참여',
                       'public': 'true', 'collaboration': True, 'evidence': '부스 참가를 모집합니다'}):
            with self.subTest(event=event):
                Signal.objects.all().delete()
                self.run_ig([media(caption='10월 20일 북페어에 저희 출판사가 참여합니다.')],
                            {'items': [verdict(type='event', event=event)]})
                self.assertEqual(self.peers.candidate_items(TODAY, NOW), [])
        Signal.objects.all().delete()
        self.run_ig([media(caption='출판사 부스 참가를 모집합니다. 날짜는 곧 알려드립니다.')],
                    {'items': [verdict(type='event', event={'date': '2026-10-20', 'name': '북페어',
                        'public': True, 'collaboration': True, 'opportunity': '부스 참여',
                        'evidence': '출판사 부스 참가를 모집합니다'})]})
        self.assertEqual(self.peers.candidate_items(TODAY, NOW), [])

    def test_sensitive_cancelled_past_and_far_events_are_not_candidates(self):
        for i, fields in enumerate(({'sensitive': True}, {'cancelled': True}, {}, {})):
            day = ('2026-10-20', '2026-10-20', '2026-10-12', '2026-12-20')[i]
            event = {'date': day, 'name': '북페어', 'place': '', 'opportunity': '부스 참여',
                     'public': True, 'collaboration': True, 'evidence': '출판사 부스 참가를 모집합니다'}
            text = f'{day} 북페어. 출판사 부스 참가를 모집합니다.'
            self.run_ig([media(str(i), caption=text)], {'items': [verdict(type='event', event=event, **fields)]})
        self.assertEqual(self.peers.candidate_items(TODAY, NOW), [])

    def test_blog_normalizes_postview_links_without_collapsing_different_posts(self):
        source = self.peers.Source('blog', 'testpress', '참고 출판사')
        xml = b'''<rss><channel><item><title>Editorial</title>
          <link>https://blog.naver.com/PostView.naver?blogId=testpress&amp;logNo=123&amp;foo=x</link>
          <pubDate>Tue, 13 Oct 2026 09:00:00 +0900</pubDate><description>Editorial note.</description></item>
          <item><title>Other</title><link>https://m.blog.naver.com/testpress/124?utm_source=x</link>
          <pubDate>Mon, 12 Oct 2026 09:00:00 +0900</pubDate></item></channel></rss>'''
        report = self.peers.run(FakeLLM({'items': [verdict(0), verdict(1)]}), TODAY, NOW, sources=[source],
                                fetch_rss=lambda *a, **kw: xml)
        self.assertEqual(len(report.new), 2)
        self.assertEqual(set(Signal.objects.values_list('url', flat=True)),
                         {'https://blog.naver.com/testpress/123', 'https://blog.naver.com/testpress/124'})
        self.assertEqual(len(set(Signal.objects.values_list('key', flat=True))), 2)

    def test_invalid_rss_is_failure_not_empty_success(self):
        source = self.peers.Source('blog', 'testpress', '참고 출판사')
        report = self.peers.run(FakeLLM([]), TODAY, NOW, sources=[source],
                                fetch_rss=lambda *a, **kw: b'<html>Login required</html>')
        self.assertIn('blog:testpress', report.failures)
        self.assertFalse(WorkerState.get('peer_scan_state')['sources']['blog:testpress'].get('success_at'))

    def test_edited_source_cancellation_rechecks_same_identity(self):
        caption = '10월 20일 북페어. 출판사 부스 참가를 모집합니다.'
        event = {'date': '2026-10-20', 'name': '북페어', 'place': '', 'opportunity': '부스 참가 검토',
                 'public': True, 'collaboration': True, 'evidence': '출판사 부스 참가를 모집합니다'}
        self.run_ig([media(caption=caption)], {'items': [verdict(type='event', event=event)]})
        self.assertEqual(len(self.peers.candidate_items(TODAY, NOW)), 1)
        result = self.run_ig([media(caption=caption + ' 모집을 취소합니다.')],
                             {'items': [verdict(type='event', event=event, cancelled=True)]})
        self.assertEqual(result.new, [])
        self.assertEqual(Signal.objects.count(), 1)
        self.assertEqual(self.peers.candidate_items(TODAY, NOW), [])

    def test_malformed_safety_flags_are_retryable_not_assumed_safe(self):
        report = self.run_ig([media()], {'items': [verdict(sensitive='true')]})
        self.assertEqual(Signal.objects.count(), 0)
        self.assertIn('ig:testpress', report.failures)

    def test_changed_source_failed_recheck_temporarily_removes_old_opportunity(self):
        caption = '10월 20일 북페어. 출판사 부스 참가를 모집합니다.'
        event = {'date': '2026-10-20', 'name': '북페어', 'place': '', 'opportunity': '부스 참가 검토',
                 'public': True, 'collaboration': True, 'evidence': '출판사 부스 참가를 모집합니다'}
        self.run_ig([media(caption=caption)], {'items': [verdict(type='event', event=event)]})
        self.assertEqual(len(self.peers.candidate_items(TODAY, NOW)), 1)
        changed = media(caption=caption + ' 참가 조건이 변경되었습니다.')
        self.run_ig([changed], {'items': []})
        self.assertEqual(self.peers.candidate_items(TODAY, NOW), [])
        self.run_ig([changed], {'items': [verdict(type='event', event=event)]})
        self.assertEqual(len(self.peers.candidate_items(TODAY, NOW)), 1)

    def test_sent_cross_channel_event_does_not_reappear_from_duplicate_source(self):
        caption = '10월 20일 북페어. 출판사 부스 참가를 모집합니다.'
        event = {'date': '2026-10-20', 'name': '북페어', 'place': '', 'opportunity': '부스 참가 검토',
                 'public': True, 'collaboration': True, 'evidence': '출판사 부스 참가를 모집합니다'}
        self.run_ig([media(caption=caption)], {'items': [verdict(type='event', event=event)]})
        first = Signal.objects.get()
        duplicate = Signal.objects.create(kind='peer', key='peer:blog:duplicate', title=first.title,
                                          url='https://blog.naver.com/testpress/2', detail=first.detail,
                                          relevant=True, happens_on=first.happens_on)
        Proposal.objects.create(kind=Proposal.NOW, candidate_key=f'peer:{duplicate.id}', headline='x', sent_at=NOW)
        self.assertEqual(self.peers.candidate_items(TODAY, NOW), [])

    def test_briefing_uses_account_baseline_and_at_most_two_different_publishers(self):
        sources = [self.source, self.peers.Source('ig', 'bigpress', '큰 출판사')]
        rows = {'testpress': [media('small', likes=30)] + [media(f's{i}', age=20+i, likes=10) for i in range(5)],
                'bigpress': [media('big', likes=200)] + [media(f'b{i}', age=20+i, likes=200) for i in range(5)]}
        self.peers.run(FakeLLM({'items': [verdict()]}), TODAY, NOW, sources=sources,
                       business_media=lambda account, **kw: rows[account])
        lines = self.peers.briefing_lines(TODAY, NOW)
        self.assertEqual(len(lines), 2)
        self.assertIn('참고 출판사', lines[0])
        self.assertIn('3.0배', lines[0])
        self.assertIn('광고 여부', lines[0])
        self.assertNotIn('자연', '\n'.join(lines))

    def test_small_baseline_never_claims_relative_performance(self):
        self.run_ig([media(likes=100)] + [media(f'b{i}', age=20+i) for i in range(4)])
        [line] = self.peers.briefing_lines(TODAY, NOW)
        self.assertNotIn('배', line)
        self.assertIn('비교할 글', line)
        WorkerState.put('peer_mode', 'off')
        self.assertEqual(self.peers.briefing_lines(TODAY, NOW), [])

    def test_summary_rejects_unmentioned_short_numbers_and_decimal_amounts(self):
        caption = '10월 20일 북페어. 출판사 부스 참가를 모집합니다.'
        for summary in ('50개 출판사가 참여하는 북페어.', '참가비는 1원.', '참가비는 0원.', '참가비는 1.5원.'):
            with self.subTest(summary=summary):
                Signal.objects.all().delete()
                report = self.run_ig([media(caption=caption)], {'items': [verdict(summary=summary)]})
                self.assertEqual(Signal.objects.count(), 0)
                self.assertIn('ig:testpress', report.failures)

    def test_opportunity_rejects_unmentioned_short_numbers(self):
        caption = '10월 20일 북페어. 출판사 부스 참가를 모집합니다.'
        event = {'date': '2026-10-20', 'name': '북페어', 'place': '', 'opportunity': '참가비 99원, 최대 50곳',
                 'public': True, 'collaboration': True, 'evidence': '출판사 부스 참가를 모집합니다'}
        self.run_ig([media(caption=caption)], {'items': [verdict(type='event', event=event)]})
        self.assertEqual(self.peers.candidate_items(TODAY, NOW), [])
        self.assertIsNone(Signal.objects.get().detail['event'])

    def test_source_supported_short_numbers_and_commas_survive(self):
        caption = '10월 20일 북페어. 출판사 부스 참가를 모집합니다. 참가비 1,000원, 최대 50곳입니다.'
        event = {'date': '2026-10-20', 'name': '북페어', 'place': '', 'opportunity': '참가비 1000원, 최대 50곳',
                 'public': True, 'collaboration': True, 'evidence': '출판사 부스 참가를 모집합니다'}
        self.run_ig([media(caption=caption)], {'items': [verdict(type='event', event=event,
                    summary='10월 20일 북페어가 최대 50곳의 출판사를 모집한다.')]})
        self.assertEqual(len(self.peers.candidate_items(TODAY, NOW)), 1)

    def test_can_send_rechecks_later_cross_channel_cancellation(self):
        self.assertTrue(callable(getattr(self.peers, 'can_send', None)), '발송 직전 행사 재검증이 필요합니다')
        caption = '10월 20일 북페어. 출판사 부스 참가를 모집합니다.'
        event = {'date': '2026-10-20', 'name': '북페어', 'place': '', 'opportunity': '부스 참가 검토',
                 'public': True, 'collaboration': True, 'evidence': '출판사 부스 참가를 모집합니다'}
        self.run_ig([media(caption=caption)], {'items': [verdict(type='event', event=event)]})
        signal = Signal.objects.get()
        proposal = Proposal.objects.create(kind=Proposal.NOW, signal=signal, candidate_key=f'peer:{signal.id}',
                                            headline='북페어 참가 검토', extra={'more_signal_ids': []})
        self.assertTrue(self.peers.can_send(proposal, TODAY, NOW))
        Signal.objects.create(kind='peer', key='peer:blog:later-cancel', title='같은 북페어 취소',
                              relevant=False, happens_on=signal.happens_on,
                              detail={**signal.detail, 'cancelled': True, 'channel': 'blog'})
        self.assertEqual(self.peers.candidate_items(TODAY, NOW), [])
        self.assertFalse(self.peers.can_send(proposal, TODAY, NOW))

    def test_can_send_ignores_proposal_sent_mark_and_reads_fresh_signal_state(self):
        self.assertTrue(callable(getattr(self.peers, 'can_send', None)), '발송 직전 행사 재검증이 필요합니다')
        caption = '10월 20일 북페어. 출판사 부스 참가를 모집합니다.'
        event = {'date': '2026-10-20', 'name': '북페어', 'place': '', 'opportunity': '부스 참가 검토',
                 'public': True, 'collaboration': True, 'evidence': '출판사 부스 참가를 모집합니다'}
        self.run_ig([media(caption=caption)], {'items': [verdict(type='event', event=event)]})
        signal = Signal.objects.get()
        proposal = Proposal.objects.create(kind=Proposal.NOW, signal=signal, candidate_key=f'peer:{signal.id}',
                                            headline='북페어 참가 검토', sent_at=NOW)
        self.assertEqual(self.peers.candidate_items(TODAY, NOW), [])
        self.assertTrue(self.peers.can_send(proposal, TODAY, NOW))
        Signal.objects.filter(pk=signal.pk).update(sensitive=True)
        self.assertFalse(self.peers.can_send(proposal, TODAY, NOW))
        Signal.objects.filter(pk=signal.pk).update(sensitive=False)
        self.assertFalse(self.peers.can_send(proposal, date(2026, 10, 21), NOW + timedelta(days=7)))
        WorkerState.put('peer_mode', 'off')
        self.assertFalse(self.peers.can_send(proposal, TODAY, NOW))

    def test_separate_cancellation_source_without_open_invitation_closes_existing_event(self):
        caption = '10월 20일 북페어. 출판사 부스 참가를 모집합니다.'
        event = {'date': '2026-10-20', 'name': '북페어', 'place': '', 'opportunity': '부스 참가 검토',
                 'public': True, 'collaboration': True, 'evidence': '출판사 부스 참가를 모집합니다'}
        self.run_ig([media(caption=caption)], {'items': [verdict(type='event', event=event)]})
        cancellation = {**event, 'collaboration': False, 'opportunity': '', 'evidence': '북페어를 취소합니다'}
        self.run_ig([media('cancel', caption='10월 20일 북페어를 취소합니다.')],
                    {'items': [verdict(type='event', cancelled=True, event=cancellation)]})
        self.assertEqual(self.peers.candidate_items(TODAY, NOW), [])
