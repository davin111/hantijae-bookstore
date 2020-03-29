# -*- encoding: utf-8 -*-
from rest_framework import serializers

from books.models import Book

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
        )
