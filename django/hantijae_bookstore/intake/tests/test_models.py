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


class RenameReviewersMigrationTest(TestCase):
    """0003 은 옛 저장값('family')을 역할 이름으로 옮긴다. 테스트 DB는 마이그레이션 없이 만들어지므로 함수를 직접 부른다."""
    def test_moves_chat_kind_and_warning_audience(self):
        import importlib
        from datetime import date
        from django.apps import apps
        from books.models import Book, Category
        from intake.models import BookDraft, IntakeSource, TelegramChat
        mig = importlib.import_module('intake.migrations.0003_role_based_names')
        TelegramChat.objects.create(chat_id=-1, kind='family')
        book = Book.objects.create(title='t', full_price=1, page_count=1, published_date=date(2026, 1, 1),
                                   category=Category.objects.create(name='c'))
        old = {'code': 'x', 'message': 'm', 'blocking': False, 'audience': 'family'}
        draft = BookDraft.objects.create(source=IntakeSource.objects.create(kind='drive', title='s'), book=book,
                                         warnings=[old, dict(old, audience='admin')], extracted={'_notes': [old]})
        mig.forwards(apps, None)
        self.assertEqual(TelegramChat.objects.get(chat_id=-1).kind, 'reviewers')
        draft.refresh_from_db()
        self.assertEqual([w['audience'] for w in draft.warnings], ['reviewer', 'admin'])
        self.assertEqual(draft.extracted['_notes'][0]['audience'], 'reviewer')
        mig.backwards(apps, None)
        self.assertEqual(TelegramChat.objects.get(chat_id=-1).kind, 'family')
