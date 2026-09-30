"""도서관 정보나루 대출을 지금 한 번 읽고, 대출 후보와 구글 검색 줄을 보여 준다(운영 점검용).
--dry-run: 기록하지 않는다(트랜잭션을 되돌린다). --book: 책 id(여러 번 가능)."""
from contextlib import nullcontext

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from books.models import Book
from marketing import candidates, loans, search
from marketing.timeutil import kst_today


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = '도서관 대출 수집·후보·검색 줄 확인 (--dry-run이면 기록하지 않음)'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='기록하지 않음(정보나루는 실제로 부른다 — --book 없이 쓰면 170권 넘게, 하루 한도 500번)')
        parser.add_argument('--book', type=int, action='append', default=[])

    def handle(self, *args, dry_run=False, book=(), **options):
        today = kst_today(timezone.now())
        books = list(Book.objects.filter(id__in=book)) if book else None
        try:
            with transaction.atomic() if dry_run else nullcontext():
                r = loans.collect(today, books=books)
                self.stdout.write(f'책 {r.books}권, 기록 {r.saved}건, 도서관 자료에 없음 {r.missing}권, 실패 {r.failed}권')
                for c in candidates.loan_candidates(today):
                    self.stdout.write(f'- 『{c.books[0].title}』 {c.summary}')
                self.stdout.write(search.week_line(today) or '(구글 검색 줄 없음)')
                if dry_run:
                    raise _Rollback
        except _Rollback:
            self.stdout.write('(dry-run: 기록하지 않았어요)')
