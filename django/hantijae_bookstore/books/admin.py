from django.contrib import admin
from django.utils.safestring import mark_safe
from books.models import Author, Book, BookAuthor, BookSeries, Category, Series


class BookAuthorInline(admin.TabularInline):
    model = BookAuthor
    extra = 1


class BookSeriesInline(admin.TabularInline):
    model = BookSeries
    extra = 1


class BookAdmin(admin.ModelAdmin):
    list_filter = ['series__series', 'category']
    actions = ['set_visible', 'set_invisible']
    list_display = ['id', 'title', 'subtitle', 'full_price', 'author_list', 'series_list', 'category', 'published_date', '_visible']
    fields = ['title', 'subtitle', 'short_description', 'description', 'full_price', 'price', 'isbn', 'page_count',
              'size', 'category', 'published_date', 'visible', 'kyobo_url', 'aladin_url', 'yes24_url', 'interpark_url']
    search_fields = ['title', 'subtitle', 'authors__author__name']
    inlines = [BookAuthorInline, BookSeriesInline]

    def author_list(self, book):
        book_authors = book.authors.all()
        result = '<div>'
        for book_author in book_authors:
            author = book_author.author
            result += f'<a href="/admin/books/author/{author.id}/">{author.id}: {author} - {BookAuthor.TYPE_TO_KOREAN[book_author.author_type]}</a><br />'
        result += u'</div>'
        return mark_safe(result)

    author_list.short_description = '저자'

    def series_list(self, book):
        book_all_series = book.series.all()
        result = '<div>'
        for book_series in book_all_series:
            series = book_series.series
            result += f'<a href="/admin/books/series/{series.id}/">{series} - {book_series.index}</a><br />'
        result += u'</div>'
        return mark_safe(result)

    series_list.short_description = '시리즈'

    def _visible(self, book):
        return book.visible

    _visible.short_description = '판매 중'
    _visible.boolean = True

    def set_visible(self, request, queryset):
        rows_updated = queryset.update(visible=True)
        self.message_user(request, f"{rows_updated} 권의 책을 '절판'으로 표시했습니다.")

    set_visible.short_description = "'절판'으로 표시하기"

    def set_invisible(self, request, queryset):
        rows_updated = queryset.update(visible=False)
        self.message_user(request, f"{rows_updated} 권의 책의 '절판' 표시를 취소했습니다.")

    set_invisible.short_description = "'절판' 표시 취소하기"


class AuthorAdmin(admin.ModelAdmin):
    list_filter = ['entity_type']
    list_display = ['id', 'name', 'email', 'phone_number', 'address']
    search_fields = ['name']


admin.site.register(Book, BookAdmin)
admin.site.register(Author, AuthorAdmin)
admin.site.register(Category)
admin.site.register(Series)
