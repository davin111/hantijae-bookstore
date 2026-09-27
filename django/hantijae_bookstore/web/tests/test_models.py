from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from web.models import Notice, current_notice


class NoticeTest(TestCase):
    def test_active_filters_state_and_window_newest_first(self):
        now = timezone.now()
        old = Notice.objects.create(message='예전', starts_at=now - timedelta(days=3), ends_at=now + timedelta(days=1))
        new = Notice.objects.create(message='새것', starts_at=now - timedelta(days=1), ends_at=None)
        Notice.objects.create(message='초안', state=Notice.DRAFT, starts_at=now - timedelta(days=1))
        Notice.objects.create(message='끝남', starts_at=now - timedelta(days=5), ends_at=now - timedelta(seconds=1))
        Notice.objects.create(message='예약', starts_at=now + timedelta(days=1))
        Notice.objects.create(message='내림', state=Notice.REMOVED, starts_at=now - timedelta(days=1))
        self.assertEqual(list(Notice.objects.active(now)), [new, old])
        self.assertEqual(current_notice(now), new)

    def test_current_notice_none(self):
        self.assertIsNone(current_notice())

    def test_defaults(self):
        n = Notice.objects.create(message='알림')
        self.assertEqual(n.state, Notice.POSTED)
        self.assertEqual(n.link_label, '자세히 보기')
        self.assertIsNotNone(n.starts_at)
