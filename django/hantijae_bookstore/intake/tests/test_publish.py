from datetime import date
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from books.models import Book, Category
from intake import publish
from intake.drafts import StaleError
from intake.models import BookDraft, IntakeSource


class PublishTest(TestCase):
    def setUp(self):
        cat = Category.objects.create(name='에세이')
        self.book = Book.objects.create(title='책', full_price=1, page_count=100, category=cat,
                                        published_date=date(2026, 1, 1), is_published=False)
        src = IntakeSource.objects.create(kind=IntakeSource.DRIVE, title='x')
        self.draft = BookDraft.objects.create(source=src, book=self.book, state=BookDraft.REVIEW,
                                              extracted={'_unresolved': [], '_edited': [], '_notes': [], '_source_quality': 0.9})

    def test_blocked_when_blocking_warnings(self):
        with self.assertRaises(publish.PublishBlocked) as ctx:   # 표지 없음 → 차단
            publish.publish(self.draft.id, self.draft.version)
        self.assertIn('no_front_cover', {w['code'] for w in ctx.exception.warnings})
        self.assertFalse(Book.objects.get(pk=self.book.id).is_published)

    def test_publish_flips_flag_and_clears_caches(self):
        cache.set('book_count', 999)
        with mock.patch('intake.publish.check_book', return_value=[]):
            draft = publish.publish(self.draft.id, self.draft.version)
        self.assertEqual(draft.state, BookDraft.PUBLISHED)
        self.assertTrue(Book.objects.get(pk=self.book.id).is_published)
        self.assertIsNone(cache.get('book_count'))

    def test_stale_version(self):
        with self.assertRaises(StaleError):
            publish.publish(self.draft.id, self.draft.version + 5)
