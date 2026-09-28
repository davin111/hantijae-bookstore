import tempfile
from datetime import datetime, timezone
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from context.models import ContextEntry, Participant
from context.tests.export_fixture import write_fixture

GROUP = -259
CMD = 'context.management.commands.context_import_telegram.timezone.now'
NOW = datetime(2026, 9, 29, 3, 0, tzinfo=timezone.utc)


class ImportCommandTest(TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        write_fixture(self.dir)
        Participant.objects.create(role='봇', aliases='한티재봇')
        Participant.objects.create(role='운영진A', aliases='대표님')

    def run_cmd(self, *args, now=NOW):
        out = StringIO()
        with mock.patch(CMD, return_value=now):
            call_command('context_import_telegram', self.dir, '--chat-id', str(GROUP), *args, stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing_and_reports(self):
        out = self.run_cmd('--dry-run')
        self.assertFalse(ContextEntry.objects.exists())
        self.assertIn('전화 1', out)
        self.assertIn('대표님(운영진A) 2건', out)
        self.assertIn('편집장님(참여자) 1건', out)
        self.assertIn('봇 메시지 2', out)
        self.assertNotIn('010-1234-5678', out)

    def test_import_masks_skips_bot_and_is_idempotent(self):
        self.run_cmd()
        self.run_cmd()
        self.assertEqual(set(ContextEntry.objects.values_list('key', flat=True)),
                         {f'tgx:{GROUP}:100', f'tgx:{GROUP}:101', f'tgx:{GROUP}:104'})
        first = ContextEntry.objects.get(key=f'tgx:{GROUP}:100')
        self.assertEqual((first.text, first.role, first.origin), ('다음 주 북토크 [전화]\n장소 & 시간', '운영진A', 'export'))
        self.assertEqual(ContextEntry.objects.get(key=f'tgx:{GROUP}:101').reply_to_id, 100)
        forwarded = ContextEntry.objects.get(key=f'tgx:{GROUP}:104')
        self.assertEqual((forwarded.reply_to_bot, forwarded.forwarded, forwarded.media), (True, True, 'contact'))

    def test_window_is_recent_days_and_before_first_live_record(self):
        ContextEntry.objects.create(key=f'tg:{GROUP}:5', chat_id=GROUP, origin='live',
                                    at=datetime(2026, 9, 27, 13, 17, 30, tzinfo=timezone.utc))   # 22:17:30 KST
        out = self.run_cmd('--days', '1', now=datetime(2026, 9, 28, 13, 15, tzinfo=timezone.utc))  # 22:15 KST
        keys = set(ContextEntry.objects.filter(origin='export').values_list('key', flat=True))
        self.assertEqual(keys, {f'tgx:{GROUP}:101'})     # 100은 하루보다 오래됨, 104는 실시간 기록 뒤
        self.assertIn('기간 밖 1', out)
        self.assertIn('실시간 기록 이후 1', out)

    def test_reimport_does_not_restore_forgotten_rows(self):
        from context.record import forget
        self.run_cmd()
        first = ContextEntry.objects.get(key=f'tgx:{GROUP}:100')
        forget(GROUP, 0, sent_at=first.at)
        out = self.run_cmd()
        self.assertEqual(ContextEntry.objects.get(key=f'tgx:{GROUP}:100').text, '')
        self.assertNotIn('다시 돌리세요', out)
