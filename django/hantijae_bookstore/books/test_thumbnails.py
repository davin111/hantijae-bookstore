import io
from datetime import date
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from PIL import Image

from books.models import Book, Category
from books.thumbnails import THUMB_MAX_SIDE


def png(w=1000, h=1500, mode='RGBA'):
    buf = io.BytesIO()
    Image.new(mode, (w, h), (200, 30, 30, 0) if mode == 'RGBA' else (200, 30, 30)).save(buf, 'PNG')
    return SimpleUploadedFile('cover.png', buf.getvalue(), content_type='image/png')


class ThumbnailTest(TestCase):
    def make(self, **kw):
        return Book.objects.create(title='표지 책', full_price=10000, page_count=100, published_date=date(2026, 1, 1),
                                   category=Category.objects.get_or_create(name='인문')[0], **kw)

    def test_saving_with_cover_creates_jpeg_thumbnail(self):
        b = self.make(cover_image=png())
        b.refresh_from_db()
        self.assertTrue(b.cover_thumbnail.name.startswith('book-cover-thumbnail/'))
        with b.cover_thumbnail.open('rb') as fh, Image.open(fh) as im:
            self.assertEqual(im.format, 'JPEG')
            self.assertEqual(max(im.size), THUMB_MAX_SIDE)
            self.assertEqual(im.getpixel((5, 5)), (255, 255, 255))  # 투명 배경은 흰색으로

    def test_resave_without_cover_change_keeps_thumbnail(self):
        b = self.make(cover_image=png())
        first = Book.objects.get(pk=b.pk).cover_thumbnail.name
        b = Book.objects.get(pk=b.pk)
        with mock.patch('books.thumbnails.make_thumbnail_bytes') as maker:
            b.title = '제목만 바꿈'
            b.save()
            maker.assert_not_called()
        self.assertEqual(Book.objects.get(pk=b.pk).cover_thumbnail.name, first)

    def test_changing_cover_regenerates(self):
        b = self.make(cover_image=png())
        first = Book.objects.get(pk=b.pk).cover_thumbnail.name
        b = Book.objects.get(pk=b.pk)
        b.cover_image = png(600, 900, 'RGB')
        b.save()
        self.assertNotEqual(Book.objects.get(pk=b.pk).cover_thumbnail.name, first)

    def test_broken_cover_does_not_block_save(self):
        b = self.make(cover_image=SimpleUploadedFile('cover.png', b'not an image', content_type='image/png'))
        self.assertFalse(Book.objects.get(pk=b.pk).cover_thumbnail)

    def test_book_without_cover_is_untouched(self):
        self.assertFalse(Book.objects.get(pk=self.make().pk).cover_thumbnail)

    def test_deferred_loading_does_not_query_cover(self):
        self.make(cover_image=png())
        with self.assertNumQueries(1):
            list(Book.objects.only('id', 'updated_at'))

    def test_command_fills_missing_only_unless_force(self):
        b = self.make(cover_image=png())
        Book.objects.filter(pk=b.pk).update(cover_thumbnail='')
        call_command('make_cover_thumbnails')
        filled = Book.objects.get(pk=b.pk).cover_thumbnail.name
        self.assertTrue(filled)
        call_command('make_cover_thumbnails')
        self.assertEqual(Book.objects.get(pk=b.pk).cover_thumbnail.name, filled)
        call_command('make_cover_thumbnails', '--force')
        self.assertNotEqual(Book.objects.get(pk=b.pk).cover_thumbnail.name, filled)
