from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.serializers import SimpleUserSerializer, UserSerializer

class UserViewSet(viewsets.GenericViewSet):
    serializer_class = SimpleUserSerializer

    def get_serializer_class(self):
        if self.action == 'me':
            return UserSerializer
        return self.serializer_class

    @action(detail=False, methods=['PUT'])
    def login(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return Response(SimpleUserSerializer(user).data)
        else:
            return Response(status=status.HTTP_403_FORBIDDEN)

    @action(detail=False, methods=['GET'])
    def logout(self, request):
        if request.user.is_authenticated:
            logout(request)
            return Response()
        return Response(status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['GET'])
    def me(self, request):
        user = request.user
        if user.is_authenticated:
            return Response(UserSerializer(user).data)
        return Response(status=status.HTTP_403_FORBIDDEN)
