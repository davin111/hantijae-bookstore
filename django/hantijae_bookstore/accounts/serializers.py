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
