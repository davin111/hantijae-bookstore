from datetime import date
from itertools import count

from books.models import Author, Book, BookAuthor, BookSeries, Category, Series

_seq = count(100000)


def category():
    return Category.objects.get_or_create(name='인문')[0]


def series(name='단행본'):
    return Series.objects.get_or_create(name=name, defaults={'series_type': Series.SERIES})[0]


def book(title='책', published=date(2026, 1, 1), in_series='단행본', authors=(('지은이', 1),), **fields):
    values = dict(subtitle='', short_description='', description='', full_price=15000, page_count=200,
                  size='130*204', isbn=f'979-11-{next(_seq)}-00-0', category=category(), published_date=published)
    values.update(fields)
    b = Book.objects.create(title=title, **values)
    for name, role in authors:
        author = Author.objects.filter(name=name).first() or Author.objects.create(name=name)
        BookAuthor.objects.create(book=b, author=author, author_type=role)
    if in_series:
        BookSeries.objects.create(book=b, series=series(in_series))
    return b
