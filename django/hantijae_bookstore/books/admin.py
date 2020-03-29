from django.contrib import admin
from books.models import Book, Author, Category, Series


admin.site.register(Book)
admin.site.register(Author)
admin.site.register(Category)
admin.site.register(Series)
