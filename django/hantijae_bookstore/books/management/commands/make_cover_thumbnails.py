from django.core.management.base import BaseCommand
from django.db.models import Q

from books.models import Book
from books.thumbnails import refresh_cover_thumbnail


class Command(BaseCommand):
    help = '목록 카드용 축소 표지를 만든다 (없는 책만, --force 면 전부 다시)'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **options):
        qs = Book.objects.exclude(Q(cover_image='') | Q(cover_image__isnull=True))
        if not options['force']:
            qs = qs.filter(Q(cover_thumbnail='') | Q(cover_thumbnail__isnull=True))
        ok = failed = 0
        for book in qs.order_by('id').iterator():
            if refresh_cover_thumbnail(book):
                ok += 1
            else:
                failed += 1
        self.stdout.write(f'썸네일 생성 {ok}권, 실패 {failed}권')
