import uuid

from django.core.validators import FileExtensionValidator
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
    SERIES = 1
    NORMAL = 2

    SERIES_TYPES = (
        (SERIES, 'series'),
        (NORMAL, 'normal'),
    )

    name = models.CharField(max_length=300)
    series_type = models.IntegerField(choices=SERIES_TYPES, default=SERIES)

    class Meta:
        db_table = 'books_series'

    def __str__(self):
        return self.name


class Book(BaseModel):
    def cover_image_path(self, filename):
        extension = filename.split('.')[-1]
        return "book-cover-image/{}.{}".format(uuid.uuid4(), extension)

    def cover_image_3d_path(self, filename):
        extension = filename.split('.')[-1]
        return "book-cover-image-3d/{}.{}".format(uuid.uuid4(), extension)

    def cover_thumbnail_path(self, filename):
        return "book-cover-thumbnail/{}.jpg".format(uuid.uuid4())

    title = models.CharField(null=False, blank=False, max_length=500)
    subtitle = models.CharField(null=False, blank=True, max_length=1000)
    short_description = models.TextField(null=False, blank=True)
    description = models.TextField(null=False, blank=True)
    full_price = models.PositiveSmallIntegerField(null=False)
    price = models.PositiveSmallIntegerField(null=True, blank=True)
    isbn = models.CharField(unique=True, null=True, max_length=200)
    page_count = models.PositiveSmallIntegerField()
    size = models.CharField(max_length=100, null=True)
    category = models.ForeignKey(Category, related_name='books', on_delete=models.CASCADE)
    published_date = models.DateField(db_index=True)
    visible = models.BooleanField(default=True, help_text="판매 중")
    is_published = models.BooleanField(default=True, db_index=True,
                                       help_text="사이트 공개 여부 (해제 = 검수 중 초안)")
    kyobo_url = models.URLField(max_length=500, null=False, blank=True)
    aladin_url = models.URLField(max_length=500, null=False, blank=True)
    yes24_url = models.URLField(max_length=500, null=False, blank=True)
    interpark_url = models.URLField(max_length=500, null=False, blank=True)
    cover_image = models.FileField(max_length=255, upload_to=cover_image_path, null=True, blank=True,
                                   validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png"])])
    cover_image_3d = models.FileField(max_length=255, upload_to=cover_image_3d_path, null=True, blank=True,
                                      validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png"])])
    cover_thumbnail = models.FileField(max_length=255, upload_to=cover_thumbnail_path, null=True, blank=True,
                                       editable=False, help_text="목록 카드용 축소 표지 (표지를 바꾸면 자동 생성)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # .only()로 지연 로딩된 필드는 건드리지 않는다 — self.cover_image 로 읽으면 책마다 쿼리가 하나씩 더 나간다
        raw = self.__dict__.get('cover_image')
        self._cover_name_at_load = getattr(raw, 'name', raw) or ''

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cover = self.cover_image.name if self.cover_image else ''
        if cover and (cover != self._cover_name_at_load or not self.cover_thumbnail):
            from books.thumbnails import refresh_cover_thumbnail  # 모델 로딩 순서 때문에 지연 import
            refresh_cover_thumbnail(self)
        self._cover_name_at_load = cover

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
    email = models.EmailField(null=True, blank=True)
    address = models.CharField(null=True, blank=True, max_length=1500)
    phone_number = models.CharField(null=True, blank=True, max_length=100)
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
        (NORMAL, '저자'),
        (TRANSLATOR, '번역자'),
        (PLANNER, '기획자'),
        (COMPILER, '엮은이')
    )

    TYPE_TO_KOREAN = {k: v for k, v in AUTHOR_TYPES}

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
    index = models.CharField(null=True, blank=True, max_length=50)

    class Meta:
        db_table = 'books_bookseries'

    def __str__(self):
        return f'{self.book.title} - {self.series.name}'
