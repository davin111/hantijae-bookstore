from django.test import TestCase

from intake.models import IntakeSource, WorkerState


class WorkerStateTest(TestCase):
    def test_get_default_and_put(self):
        self.assertEqual(WorkerState.get('mode', 'admin_only'), 'admin_only')
        WorkerState.put('mode', 'live')
        self.assertEqual(WorkerState.get('mode', 'admin_only'), 'live')
        WorkerState.put('telegram_offset', 42)
        self.assertEqual(WorkerState.get('telegram_offset', 0), 42)


class IntakeSourceTest(TestCase):
    def test_drive_folder_id_unique_but_nullable(self):
        IntakeSource.objects.create(kind=IntakeSource.TELEGRAM, title='a')
        IntakeSource.objects.create(kind=IntakeSource.TELEGRAM, title='b')  # null 중복 허용
        IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='c', drive_folder_id='X')
        with self.assertRaises(Exception):
            IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='d', drive_folder_id='X')
