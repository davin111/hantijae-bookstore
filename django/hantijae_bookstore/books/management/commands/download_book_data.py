# coding: utf-8
from django.core.management.base import BaseCommand
from django.core.exceptions import ObjectDoesNotExist

from books.models import Book, Category, Author, Series, BookSeries, BookAuthor

TSV_FILE = '/Users/dan/Documents/hantijae-bookstore/data/한티재_도서목록200325.tsv'
STARTING_ROW = 2

def download_book_data():
    with open(TSV_FILE) as f:
        for idx, line in enumerate(f):
            if idx < STARTING_ROW:
                continue

            data = list(map(str.strip, line.split('\t')))

            category, series, title, subtitle, authors, translator, published_date, page_count, full_price, size, isbn, _, visible\
                = data[1:14]

            if not title:
                continue

            category, _ = Category.objects.get_or_create(
                name=category
            )
            print(category)

            book = Book.objects.create(
                title=title, subtitle=subtitle, published_date=published_date, page_count=int(page_count[:-1]),
                full_price=full_price.replace(',', ''), size=size, isbn=isbn, visible=bool(visible), category=category
            )
            print(book)

            if series:
                series_index = series.split()[-1]
                series_name = ' '.join(series.split(' ')[:-1])
                series, _ = Series.objects.get_or_create(name=series_name)
                bs = BookSeries.objects.create(book=book, series=series, index=series_index)
                print(bs)

            author_list = authors.replace('·', ',').split(',')
            for author_name in author_list:
                author = Author.objects.create(name=author_name)
                print(author)
                ba = BookAuthor.objects.create(book=book, author=author)
                print(ba)

class Command(BaseCommand):
    def handle(self, *args, **options):
        download_book_data()
