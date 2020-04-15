from django.contrib import admin
from django.utils.safestring import mark_safe
from books.models import Book, Author, BookAuthor, Category, Series

class BookAdmin(admin.ModelAdmin):
    list_filter = ['series__series', 'category']
    actions = ['set_visible', 'set_invisible']
    list_display = ['id', 'title', 'subtitle', 'full_price', 'author_list', 'series_list', 'category', 'published_date', '_visible']
    fields = ['title', 'subtitle', 'author_list', 'short_description', 'description', 'full_price', 'price', 'isbn', 'page_count',
              'size', 'series_list', 'category', 'published_date', 'visible']
    readonly_fields = ['author_list', 'series_list']
    search_fields = ['title', 'subtitle', 'authors__name']

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


admin.site.register(Book, BookAdmin)
admin.site.register(Author)
admin.site.register(Category)
admin.site.register(Series)
