# -*- encoding: utf-8 -*-
from rest_framework import serializers

from accounts.models import User, Basket
from books.serializers import SimpleBookSerializer


class UserSerializer(serializers.ModelSerializer):
    book_count = serializers.SerializerMethodField()
    family_name = serializers.CharField(source='last_name')
    given_name = serializers.CharField(source='first_name')

    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'email',
            'family_name',
            'given_name',
            'last_login',
            'book_count',
            'anonymous',
            'notifiable',
        )
    
    def get_book_count(self, user):
        if user.baskets.exists():
            last_basket = user.baskets.last()
            return last_basket.book_count
        return None


class SimpleBasketSerializer(serializers.ModelSerializer):
    book_count = serializers.SerializerMethodField(read_only=True)
    total_price = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Basket
        fields = (
            'id',
            'book_count',
            'max_book_count',
            'total_price',
            'max_price',
            'status',
        )

    def get_book_count(self, basket):
        return basket.book_count

    def get_total_price(self, basket):
        return basket.total_price


class BasketSerializer(serializers.ModelSerializer):
    book_count = serializers.SerializerMethodField(read_only=True)
    books = serializers.SerializerMethodField(read_only=True)
    total_price = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Basket
        fields = (
            'id',
            'books',
            'book_count',
            'max_book_count',
            'total_price',
            'max_price',
            'status',
            'info'
        )

    def get_books(self, basket):
        book_baskets = basket.books.all().order_by('-created_at')
        books = []
        for book_basket in book_baskets:
            book_data = SimpleBookSerializer(book_basket.book, context=self.context).data
            book_data['count'] = book_basket.count
            book_data['address'] = book_basket.address
            book_data['sign'] = book_basket.sign
            books.append(book_data)
        return books

    def get_book_count(self, basket):
        return basket.book_count

    def get_total_price(self, basket):
        return basket.total_price


class OrderSerializer(serializers.ModelSerializer):
    book_count = serializers.SerializerMethodField(read_only=True)
    books = serializers.SerializerMethodField(read_only=True)
    total_price = serializers.SerializerMethodField(read_only=True)
    family_name = serializers.CharField(source='last_name')
    given_name = serializers.CharField(source='first_name')
    receiver_family_name = serializers.CharField(source='receiver_last_name')
    receiver_given_name = serializers.CharField(source='receiver_first_name')

    class Meta:
        model = Basket
        fields = (
            'id',
            'books',
            'book_count',
            'max_book_count',
            'total_price',
            'max_price',
            'status',
            'family_name',
            'given_name',
            'email',
            'phone_number',
            'receiver_family_name',
            'receiver_given_name',
            'address',
            'postal_code',
            'payer',
            'info'
        )

    def get_books(self, basket):
        book_baskets = basket.books.all().order_by('-created_at')
        books = []
        for book_basket in book_baskets:
            book_data = SimpleBookSerializer(book_basket.book, context=self.context).data
            book_data['count'] = book_basket.count
            book_data['address'] = book_basket.address
            book_data['sign'] = book_basket.sign
            books.append(book_data)
        return books

    def get_book_count(self, basket):
        return basket.book_count

    def get_total_price(self, basket):
        return basket.total_price
