import os
import tempfile
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from books.models import Book, Category
from intake import drive
from intake.models import IntakeSource, WorkerState

F = drive.FOLDER


class FakeDrive:
    """{folder_id: [items]} 트리. 파일 내용은 b'x'."""
    def __init__(self, tree):
        self.tree, self.downloads = tree, []

    def list_children(self, folder_id):
        return self.tree.get(folder_id, [])

    def get(self, file_id):
        for items in self.tree.values():
            for it in items:
                if it['id'] == file_id:
                    return it
        raise KeyError(file_id)

    def download(self, file_id, dest):
        self.downloads.append(file_id)
        with open(dest, 'wb') as fh:
            fh.write(b'x')


def item(id_, name, mime='application/pdf', modified='2026-09-01T00:00:00Z', size='10'):
    return {'id': id_, 'name': name, 'mimeType': mime, 'modifiedTime': modified, 'size': size}


def tree(extra_file=None):
    book = [item('pdf', '보도자료_새책.pdf'), item('img', '새책_입체.jpg', 'image/jpeg'),
            item('psd', '새책_입체.psd', 'image/vnd.adobe.photoshop'), item('prev', '새책_미리보기', F)]
    if extra_file:
        book.append(extra_file)
    return {
        'root': [item('y2026', '2026 단행본 보도자료', F)],
        'y2026': [item('bk', '보도자료_새책', F), item('old', '보도자료_무지개를변호하다', F)],
        'bk': book,
        'prev': [item('front', '새책_앞표지.jpg', 'image/jpeg')],
        'old': [item('op', '보도자료_무지개를변호하다.pdf'), item('oi', '무지개를변호하다_입체.jpg', 'image/jpeg')],
    }


class DriveTest(TestCase):
    def setUp(self):
        cat = Category.objects.create(name='에세이')
        Book.objects.create(title='무지개를 변호하다', full_price=1, page_count=1, category=cat, published_date=date(2026, 6, 1))

    def test_title_key(self):
        self.assertEqual(drive.title_key('보도자료_P028_연대와환대'), '연대와환대')
        self.assertEqual(drive.title_key('보도자료_사그라다 파밀리아, 가족의 탄생'), '사그라다파밀리아가족의탄생')

    def test_scan_waits_for_stability_then_queues_or_ignores(self):
        fake, t0 = FakeDrive(tree()), timezone.now()
        drive.scan(fake, 'root', now=t0)
        self.assertEqual(IntakeSource.objects.filter(status=IntakeSource.SEEN).count(), 2)
        drive.scan(fake, 'root', now=t0 + timedelta(minutes=10))
        self.assertFalse(IntakeSource.objects.filter(status=IntakeSource.QUEUED).exists())
        drive.scan(fake, 'root', now=t0 + timedelta(minutes=31))
        self.assertEqual(IntakeSource.objects.get(drive_folder_id='bk').status, IntakeSource.QUEUED)
        self.assertEqual(IntakeSource.objects.get(drive_folder_id='old').status, IntakeSource.IGNORED)  # 이미 사이트에 있음

    def test_changed_fingerprint_resets_stability(self):
        t0 = timezone.now()
        drive.scan(FakeDrive(tree()), 'root', now=t0)
        drive.scan(FakeDrive(tree(item('late', '새책_앞표지2.jpg', 'image/jpeg'))), 'root', now=t0 + timedelta(minutes=31))
        self.assertEqual(IntakeSource.objects.get(drive_folder_id='bk').status, IntakeSource.SEEN)

    def test_baseline_then_ingest(self):
        n = drive.baseline(FakeDrive(tree()), 'root')
        self.assertEqual(n, 2)
        self.assertTrue(WorkerState.get('drive_baseline_at'))
        drive.scan(FakeDrive(tree()), 'root', now=timezone.now() + timedelta(hours=2))
        self.assertFalse(IntakeSource.objects.filter(status=IntakeSource.QUEUED).exists())
        src = drive.ingest(FakeDrive(tree()), 'bk')
        self.assertEqual((src.status, src.title), (IntakeSource.QUEUED, '보도자료_새책'))

    def test_download_skips_design_sources(self):
        fake, dest = FakeDrive(tree()), tempfile.mkdtemp()
        drive.download_folder(fake, 'bk', dest)
        self.assertEqual(sorted(fake.downloads), ['front', 'img', 'pdf'])
        self.assertTrue(os.path.exists(os.path.join(dest, '새책_미리보기', '새책_앞표지.jpg')))
