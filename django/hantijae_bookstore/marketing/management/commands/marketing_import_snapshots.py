"""2026-09-28 도입 전 기준선(로컬 수집 JSON)을 SalesSnapshot으로 넣는다. 같은 날 값이 있으면 건너뛴다."""
import json
from datetime import datetime

from django.core.management.base import BaseCommand

from books.models import Book
from marketing.models import SalesSnapshot


class Command(BaseCommand):
    help = '알라딘 판매 지수 기준선 JSON 가져오기'

    def add_arguments(self, parser):
        parser.add_argument('path')

    def handle(self, *args, path, **options):
        with open(path) as f:
            data = json.load(f)
        day = datetime.fromisoformat(data['collected_at'][:19]).date()
        books = {b.id: b for b in Book.objects.all()}
        made = 0
        for row in data['rows']:
            book = books.get(row.get('id'))
            if not book or not row.get('isbn_match') or row.get('sales_point') is None:
                continue
            _, created = SalesSnapshot.objects.get_or_create(
                book=book, date=day, defaults={'sales_point': row['sales_point'],
                                               'short_reviews': row.get('short_reviews') or 0,
                                               'reviews': row.get('reviews') or 0})
            made += created
        self.stdout.write(f'{day}: {made}권 넣음')
