# -*- encoding: utf-8 -*-
from rest_framework import serializers
from django.contrib.auth.models import User


class SimpleUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'email',
            'last_login',
        )


class UserSerializer(serializers.ModelSerializer):
    book_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'email',
            'last_login',
            'book_count'
        )
    
    def get_book_count(self, user):
        if user.baskets.exists():
            last_basket = user.baskets.last()
            return last_basket.books.count()
        return None
