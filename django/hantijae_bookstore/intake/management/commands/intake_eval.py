from collections import Counter

from django.core.management.base import BaseCommand

from books.models import Book, Category, Series
from intake.deps import build_deps
from intake.evaluation import EVAL_FIELDS, actual_from_data, compare, expected_from_book
from intake.extraction import run_extraction
from intake.mapping import isbn_digits, normalize_key


class Command(BaseCommand):
    help = '로컬 보도자료 폴더를 추출해 사이트 DB(정답)와 필드별로 비교한다. DB에 쓰지 않는다.'

    def add_arguments(self, parser):
        parser.add_argument('folders', nargs='+')

    def handle(self, *args, **options):
        llm = build_deps().llm
        cats = {c.name: c.id for c in Category.objects.all()}
        series = {s.name: s.id for s in Series.objects.all()}
        books = list(Book.objects.all())
        hits, total = Counter(), 0
        for folder in options['folders']:
            result = run_extraction(folder, llm, list(cats), list(series))
            actual = actual_from_data(result.data, cats, series)
            book = next((b for b in books if b.isbn and isbn_digits(b.isbn) == isbn_digits(actual['isbn'])), None) or \
                next((b for b in books if normalize_key(b.title) == normalize_key(actual['title'])), None)
            if not book:
                self.stdout.write(f'?? 정답 없음: {folder} → {actual["title"]}')
                continue
            total += 1
            res = compare(expected_from_book(book), actual)
            hits.update(k for k, ok in res.items() if ok)
            misses = [f"{k}: {expected_from_book(book)[k]!r} ≠ {actual[k]!r}" for k, ok in res.items() if not ok]
            self.stdout.write(f"{'OK' if not misses else 'NG'} #{book.id} {book.title}" + ''.join(f'\n    {m}' for m in misses))
        self.stdout.write('\n필드별 정확도 (n=%d)' % total)
        for k in EVAL_FIELDS:
            self.stdout.write(f'  {k:15s} {hits[k]}/{total}')
