from datetime import datetime
from django.test import TestCase
from intake.models import WorkerState
from marketing.timeutil import KST
from ops.health import evaluate, WARN, CALM


class ContentHealthTest(TestCase):
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
