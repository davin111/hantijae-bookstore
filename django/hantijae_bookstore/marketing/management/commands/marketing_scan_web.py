"""구글 알리미·유튜브 언급을 지금 한 번 읽는다(운영 점검용).
--dry-run: 기록하지 않는다(트랜잭션을 되돌린다). --no-judge: LLM 없이 책 찾기 결과만."""
from contextlib import nullcontext

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from books.models import Book
from marketing import mentions, reviews
from marketing.review_search import SOURCE_LABEL
from marketing.timeutil import kst_today


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = '구글 알리미·유튜브 언급 확인 (--dry-run이면 기록하지 않음)'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--no-judge', action='store_true')
        parser.add_argument('--book', type=int, nargs='+')

    def handle(self, *args, dry_run=False, no_judge=False, book=None, **options):
        today = kst_today(timezone.now())
        books = list(Book.objects.filter(id__in=book).prefetch_related('authors__author')) if book else None
        llm = None
        if not no_judge:
            from intake.deps import build_deps
            llm = build_deps().llm
        try:
            with transaction.atomic() if dry_run else nullcontext():
                report, fresh = mentions.scan(today, books=books)
                if not no_judge:
                    reviews.save_judged(llm, fresh, report)
                self.stdout.write(f'책 {report.books}권, 새 글 {report.found}건(서평 {len(report.reviews)}건), '
                                  f'기준선 {report.baseline}건, 읽지 못한 곳 {", ".join(report.failed) or "없음"}')
                for t, p, key in fresh:
                    verdict = '판별 안 함' if no_judge else ' '.join(report.verdicts.get(key, ('판정 없음', '')))
                    self.stdout.write(f'- 『{t.title}』 [{SOURCE_LABEL[p.source]}] {p.title[:50]} | {p.posted_on} | '
                                      f'{verdict.strip()} | {p.url}')
                if dry_run:
                    raise _Rollback
        except _Rollback:
            self.stdout.write('(dry-run: 기록하지 않았어요)')
