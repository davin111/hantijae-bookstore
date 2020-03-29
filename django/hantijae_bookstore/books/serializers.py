# -*- encoding: utf-8 -*-
from rest_framework import serializers

from books.models import Book, Category

class BookSerializer(serializers.ModelSerializer):
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
