from datetime import datetime
from unittest.mock import patch
from django.test import TestCase
from intake.models import WorkerState
from marketing import tasks
from marketing.tests.test_tasks import Deps
from marketing.timeutil import KST


class ContentScheduleTest(TestCase):
    def test_peer_scan_runs_once_after_0455_only_when_enabled(self):
        deps = Deps()
        calls = []
        def guard(_deps, name, now, fn):
            if name == 'peer':
                calls.append(now)
                return fn()
        with patch('marketing.tasks._guard', side_effect=guard), patch('marketing.tasks.peers.run') as run:
            tasks._run_due(deps, datetime(2026, 10, 14, 5, 0, tzinfo=KST))
            run.assert_not_called()
            WorkerState.put('peer_mode', 'live')
            tasks._run_due(deps, datetime(2026, 10, 14, 4, 54, tzinfo=KST))
            run.assert_not_called()
            tasks._run_due(deps, datetime(2026, 10, 14, 4, 55, tzinfo=KST))
            tasks._run_due(deps, datetime(2026, 10, 14, 8, 0, tzinfo=KST))
            self.assertEqual(run.call_count, 1)
            self.assertEqual(WorkerState.get('peer_last_scan'), '2026-10-14')

    def test_series_candidates_are_saved_as_blog_with_supplements(self):
        from marketing import midweek
        from marketing.candidates import Candidate
        from marketing.tests.fakes import FakeLLM
        now = datetime(2026, 10, 16, 5, 30, tzinfo=KST)
        c = Candidate('series:week:2026-10-12', 'series_week', [], '새 소식',
                      {'expected_channel': 'blog', 'series_form': 'standalone', 'source_urls': ['https://example.com/a']}, 2)
        WorkerState.put('midweek_mode', 'live')
        WorkerState.put('series_mode', 'live')
        cards = [{'show': '책 표지', 'text': ''}, {'show': '목차', 'text': ''}, {'show': '책 펼친 면', 'text': ''}]
        llm = FakeLLM({'items': [{'candidate_id': c.id, 'headline': '새 소식', 'reason': '확인한 소식',
                                'draft': {'channel': 'instagram', 'body': '원고', 'cards': cards}}]})
        with patch('marketing.series.items', return_value=[c]):
            made, dropped = midweek.build(llm, now.date(), now, 'live')
        self.assertEqual(len(made), 1, dropped)
        d = made[0].drafts.get()
        self.assertEqual(d.channel, 'blog')
        self.assertEqual(len(d.extra['cards']), 3)
        self.assertEqual(made[0].extra['source_urls'], ['https://example.com/a'])

    def test_midweek_keeps_peer_link_and_every_series_source_visible(self):
        from marketing import midweek, messages, notion_blocks
        from marketing.candidates import Candidate
        from marketing.tests.fakes import FakeLLM
        now = datetime(2026, 10, 16, 5, 30, tzinfo=KST)
        urls = ['https://example.com/news-a', 'https://example.com/news-b']
        peer_url = 'https://example.com/peer-invitation'
        peer = Candidate('peer:event:a', 'peer_event', [], '참가 모집', {'url': peer_url}, 2, link=peer_url)
        series = Candidate('series:week:2026-10-12', 'series_week', [], '이번 주',
                           {'expected_channel': 'blog', 'source_urls': urls}, 2, link='\n'.join(urls))
        WorkerState.put('midweek_mode', 'live')
        llm = FakeLLM({'items': [{'candidate_id': c.id, 'headline': c.summary, 'reason': '확인한 소식',
                                'draft': {'channel': 'blog', 'body': '초안'}} for c in (peer, series)]})
        with patch('marketing.peers.candidate_items', return_value=[peer]), patch('marketing.series.items', return_value=[series]):
            made, dropped = midweek.build(llm, now.date(), now, 'live')
        self.assertEqual(len(made), 2, dropped)
        by_key = {p.candidate_key: p for p in made}
        self.assertEqual(by_key[peer.id].extra['link'], peer_url)
        self.assertEqual(by_key[peer.id].extra['source_urls'], [peer_url])
        for url in [peer_url, *urls]:
            self.assertEqual(messages.midweek_text(made).count(url), 1)
        for p in made:
            for url in p.extra['source_urls']:
                self.assertIn(url, str(notion_blocks.item_memo(p, p.drafts.get())))
