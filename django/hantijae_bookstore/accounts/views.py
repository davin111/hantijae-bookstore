from django.contrib.auth import authenticate, login, logout
from django.contrib.sessions.models import Session
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User, Basket, BookBasket, MaxBookCountException
from accounts.serializers import UserSerializer, BasketSerializer
from accounts.utils import get_user_from_request
from books.models import Book

class UserViewSet(viewsets.GenericViewSet):
    serializer_class = UserSerializer

    @action(detail=False, methods=['PUT'])
    def login(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            session_key = request.session.session_key
            try:
                user.last_session = Session.objects.get(pk=session_key)
                user.save()
                print("session saved")
            except Session.DoesNotExist:
                pass
            return Response(UserSerializer(user).data)
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
        user = get_user_from_request(request)
        if user:
            return Response(UserSerializer(user).data)
        return Response(status=status.HTTP_403_FORBIDDEN)
        

class BasketViewSet(viewsets.GenericViewSet):
    serializer_class = BasketSerializer

    @action(detail=False, methods=['POST'])
    def book(self, request):
        book_id = request.data.get('book')
        if not book_id:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        book = get_object_or_404(Book, id=book_id)

        user = get_user_from_request(request)
        if not user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        baskets = Basket.objects.filter(user=user)
        if baskets.exists():
            basket = baskets.last()
        else:
            basket = Basket.objects.create(user=user)

        try:
            bookbasket, created = BookBasket.objects.get_or_create(book=book, basket=basket)
            if not created:
                bookbasket.count += 1
                bookbasket.save()
        except MaxBookCountException:
            return Response(status=status.HTTP_406_NOT_ACCEPTABLE)

        return Response(BasketSerializer(basket).data)
