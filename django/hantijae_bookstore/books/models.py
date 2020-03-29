from django.db import models


class Category(models.Model):
    NORMAL = 1
    SERIES = 2

    CATEGORY_TYPES = (
        (NORMAL, 'normal'),
        (SERIES, 'series'),
    )

    name = models.CharField(max_length=300, null=False, blank=False)
    category_type = models.IntegerField(choices=CATEGORY_TYPES)

    class Meta:
        db_table = 'books_category'


class Book(models.Model):
    title = models.CharField(max_length=500, null=False, blank=False)
    subtitle = models.CharField(max_length=1000, null=False, blank=False)
    short_description = models.TextField(null=False, blank=True)
    description = models.TextField(null=False, blank=True)
    full_price = models.PositiveSmallIntegerField(null=False)
    price = models.PositiveSmallIntegerField()
    isbn = models.CharField(max_length=200)
    page_count = models.PositiveSmallIntegerField()
    size = models.CharField(max_length=100)
    category = models.ForeignKey(Category, related_name='books', on_delete=models.CASCADE)

    class Meta:
        db_table = 'books_book'


class Author(models.Model):
    family_name = models.CharField(max_length=100, null=False, blank=False)
    given_name = models.CharField(max_length=100, null=False, blank=False)
    email = models.EmailField()
    address = models.CharField(max_length=1500)
    phone_number = models.CharField(max_length=100)

    class Meta:
        db_table = 'books_author'


class BookAuthor(models.Model):
    NORMAL = 1
    AUTHOR_TYPES = (
        (NORMAL, 'normal'),
    )

    book = models.ForeignKey(Book, related_name='authors', on_delete=models.CASCADE)
    author = models.ForeignKey(Author, related_name='books', on_delete=models.CASCADE)
    author_type = models.IntegerField(choices=AUTHOR_TYPES)

    class Meta:
        db_table = 'books_bookauthor'
