from django.core.files import File
from django.core.management.base import BaseCommand

from books.models import Book


def upload_book_covers():
    books = Book.objects.all().order_by("id")
    for book in books:
        if book.cover_image and book.cover_image_3d:
            continue

        title = book.title.replace(":", "").replace("!", "").replace("?", "")
        f = open(
            f"/Users/davin/Documents/hantijae-bookstore/frontend/src/components/Book/book_covers/{title}.png",
            "rb"
        )
        cover_image_file = File(f)
        book.cover_image.save(f"{title}.png", cover_image_file)
        f.close()

        f = open(
            f"/Users/davin/Documents/hantijae-bookstore/frontend/src/containers/BookDetail/book_covers_3d/{title}.png",
            "rb"
        )
        cover_image_3d_file = File(f)
        book.cover_image_3d.save(f"{title}.png", cover_image_3d_file)
        f.close()


class Command(BaseCommand):
    def handle(self, *args, **options):
        upload_book_covers()
