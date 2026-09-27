from django.contrib.sitemaps import Sitemap

from books.models import Book
from web import catalog


class StaticSitemap(Sitemap):
    protocol = 'https'
    changefreq = 'weekly'

    def items(self):
        return ['/', '/hantijae']

    def location(self, item):
        return item


class SeriesSitemap(Sitemap):
    protocol = 'https'
    changefreq = 'weekly'

    def items(self):
        return catalog.public_series()

    def location(self, series):
        return f'/series={series.id}'


class BookSitemap(Sitemap):
    protocol = 'https'
    changefreq = 'monthly'

    def items(self):
        return Book.objects.filter(is_published=True).order_by('id').only('id', 'updated_at')

    def location(self, book):
        return f'/book={book.id}'

    def lastmod(self, book):
        return book.updated_at


SITEMAPS = {'static': StaticSitemap, 'series': SeriesSitemap, 'books': BookSitemap}
