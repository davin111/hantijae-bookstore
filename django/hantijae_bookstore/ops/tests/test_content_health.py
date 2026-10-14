from datetime import datetime
from django.test import TestCase
from intake.models import WorkerState
from marketing.timeutil import KST
from ops.health import evaluate, WARN, CALM, OK


class ContentHealthTest(TestCase):
    def peer_row(self, states):
        WorkerState.put('marketing_mode', 'live')
        WorkerState.put('peer_mode', 'live')
        WorkerState.put('peer_last_scan', '2026-10-14')
        WorkerState.put('peer_scan_state', {'sources': states})
        return next(r for r in evaluate(datetime(2026, 10, 14, 10, 0, tzinfo=KST)) if r.key == 'peer')

    def test_partial_scan_cannot_count_missing_or_yesterdays_sources_as_success(self):
        from marketing.peers import SOURCES
        states = {s.key: {'success_at':'2026-10-14T05:00:00+09:00', 'failure_count':0, 'checked':1} for s in SOURCES}
        self.assertEqual(self.peer_row(states).state, OK)
        del states[SOURCES[-1].key]
        self.assertEqual(self.peer_row(states).state, WARN)
        states[SOURCES[-1].key] = {'success_at':'2026-10-13T05:00:00+09:00', 'failure_count':0, 'checked':1}
        self.assertEqual(self.peer_row(states).state, WARN)

    def test_rss_failure_is_not_reported_as_success(self):
        WorkerState.put('marketing_mode', 'live')
        WorkerState.put('midweek_mode', 'live')
        WorkerState.put('editor_mode', 'live')
        WorkerState.put('marketing_editor_state', {'period': 'editor:2026-10:2',
            'checked_at': '2026-10-16T05:30:00+09:00', 'status': 'rss_failed', 'reason': '네이버 블로그 확인 실패'})
        report = evaluate(datetime(2026, 10, 16, 10, 0, tzinfo=KST))
        rows = report.rows if hasattr(report, 'rows') else report
        row = next(r for r in rows if r.key == 'editor')
        self.assertEqual(row.state, WARN)

    def test_published_diary_is_evidence_to_skip(self):
        WorkerState.put('marketing_mode', 'live')
        WorkerState.put('midweek_mode', 'live')
        WorkerState.put('editor_mode', 'live')
        WorkerState.put('marketing_editor_state', {'period': 'editor:2026-10:1',
            'checked_at': '2026-10-14T05:30:00+09:00', 'status': 'posted', 'reason': '이번 구간 게시 확인'})
        report = evaluate(datetime(2026, 10, 14, 10, 0, tzinfo=KST))
        rows = report.rows if hasattr(report, 'rows') else report
        self.assertEqual(next(r for r in rows if r.key == 'editor').state, CALM)
