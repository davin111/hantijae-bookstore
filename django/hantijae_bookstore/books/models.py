from django.db import models

from core.models import BaseModel


class Category(BaseModel):
    NORMAL = 1

    CATEGORY_TYPES = (
        (NORMAL, 'normal'),
    )

    name = models.CharField(unique=True, max_length=255)
    category_type = models.IntegerField(choices=CATEGORY_TYPES, default=NORMAL)

    class Meta:
        db_table = 'books_category'

    def __str__(self):
        return self.name


class Series(BaseModel):
    name = models.CharField(max_length=300)
    
    class Meta:
        db_table = 'books_series'

    def __str__(self):
        return self.name


class Book(BaseModel):
    title = models.CharField(null=False, blank=False, max_length=500)
    subtitle = models.CharField(null=False, blank=False, max_length=1000)
    short_description = models.TextField(null=False, blank=True)
    description = models.TextField(null=False, blank=True)
    full_price = models.PositiveSmallIntegerField(null=False)
    price = models.PositiveSmallIntegerField(null=True)
    isbn = models.CharField(unique=True, null=True, max_length=200)
    page_count = models.PositiveSmallIntegerField()
    size = models.CharField(max_length=100, null=True)
    category = models.ForeignKey(Category, related_name='books', on_delete=models.CASCADE)
    published_date = models.DateField()
    visible = models.BooleanField(default=True)

    class Meta:
        db_table = 'books_book'

    def __str__(self):
        return self.title


class Author(BaseModel):
    HUMAN = 1
    ORGANIZATION = 2
    ENTITY_TYPES = (
        (HUMAN, 'human'),
        (ORGANIZATION, 'organization'),
    )

    name = models.CharField(max_length=300, null=False, blank=False)
    email = models.EmailField(null=True)
    address = models.CharField(null=True, max_length=1500)
    phone_number = models.CharField(null=True, max_length=100)
    entity_type = models.IntegerField(choices=ENTITY_TYPES, default=HUMAN)

    class Meta:
        db_table = 'books_author'

    def __str__(self):
        return self.name


class BookAuthor(models.Model):
    NORMAL = 1
    TRANSLATOR = 2
    PLANNER = 3
    COMPILER = 4
    AUTHOR_TYPES = (
        (NORMAL, 'normal'),
        (TRANSLATOR, 'translator'),
        (PLANNER, 'planner'),
        (COMPILER, 'compiler')
    )

    book = models.ForeignKey(Book, related_name='authors', on_delete=models.CASCADE)
    author = models.ForeignKey(Author, related_name='books', on_delete=models.CASCADE)
    author_type = models.IntegerField(choices=AUTHOR_TYPES, default=NORMAL)

    class Meta:
        db_table = 'books_bookauthor'

    def __str__(self):
        return f'{self.book.title} - {self.author.name}'


class BookSeries(models.Model):
    book = models.ForeignKey(Book, related_name='series', on_delete=models.CASCADE)
    series = models.ForeignKey(Series, related_name='books', on_delete=models.CASCADE)
    index = models.CharField(null=True, max_length=50)

    class Meta:
        db_table = 'books_bookseries'

    def __str__(self):
        return f'{self.book.title} - {self.series.name}'
