# -*- encoding: utf-8 -*-
from rest_framework import serializers

from accounts.models import User, Basket


class UserSerializer(serializers.ModelSerializer):
    book_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'email',
            'last_login',
            'book_count',
            'anonymous'
        )
    
    def get_book_count(self, user):
        if user.baskets.exists():
            last_basket = user.baskets.last()
            return last_basket.book_count
        return None


class BasketSerializer(serializers.ModelSerializer):
    book_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Basket
        fields = (
            'id',
            'book_count',
            'max_book_count',
            'max_price',
            'status',
        )

    def get_book_count(self, basket):
        return basket.book_count
