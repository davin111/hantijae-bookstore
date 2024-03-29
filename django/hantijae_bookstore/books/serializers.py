# -*- encoding: utf-8 -*-
from rest_framework import serializers

from books.models import Book, Author, Category, Series


class BookSerializer(serializers.ModelSerializer):
    authors = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = (
            'id',
            'title',
            'subtitle',
            'short_description',
            'description',
            'full_price',
            'price',
            'isbn',
            'page_count',
            'size',
            'category',
            'published_date',
            'authors',
            'visible',
            'aladin_url',
            'cover_image',
            'cover_image_3d',
        )

    def get_authors(self, book):
        book_authors = book.authors.all()
        authors = []
        for book_author in book_authors:
            author_data = AuthorSerializer(book_author.author, context=self.context).data
            author_data['author_type'] = book_author.author_type
            authors.append(
                author_data
            )
        return authors


class SimpleBookSerializer(serializers.ModelSerializer):
    authors = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = (
            'id',
            'title',
            'subtitle',
            'short_description',
            'full_price',
            'price',
            'category',
            'published_date',
            'authors',
            'visible',
            'aladin_url',
            'cover_image',
            'cover_image_3d',
        )

    def get_authors(self, book):
        book_authors = book.authors.all()
        authors = []
        for book_author in book_authors:
            author_data = AuthorSerializer(book_author.author, context=self.context).data
            author_data['author_type'] = book_author.author_type
            authors.append(
                author_data
            )
        return authors


class AuthorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Author
        fields = (
            'id',
            'name',
            'email',
            'address',
            'phone_number',
            'entity_type'
        )


class CategorySerializer(serializers.ModelSerializer):
    books = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = (
            'id',
            'name',
            'category_type',
            'books'
        )
    
    def get_books(self, category):
        return BookSerializer(category.books.all(), many=True, context=self.context).data


class SimpleSeriesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Series
        fields = (
            'id',
            'name',
        )


class SeriesSerializer(serializers.ModelSerializer):
    books = serializers.SerializerMethodField()

    class Meta:
        model = Series
        fields = (
            'id',
            'name',
            'books'
        )
    
    def get_books(self, series):
        book_all_series = series.books.all().order_by('-book__published_date')
        books = []
        for book_series in book_all_series:
            book_data = SimpleBookSerializer(book_series.book, context=self.context).data
            book_data['index'] = book_series.index
            books.append(book_data)
        return books
