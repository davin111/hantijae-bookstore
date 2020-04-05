from django.contrib.auth import authenticate, login, logout
from django.contrib.sessions.models import Session
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User, Basket, BookBasket, MaxBookCountException
from accounts.serializers import UserSerializer, BasketSerializer, SimpleBasketSerializer
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

    def list(self, request):
        user = get_user_from_request(request)
        if not user:
            return Response(status=status.HTTP_403_FORBIDDEN)

        baskets = Basket.objects.filter(user=user)
        if baskets.exists():
            basket = baskets.last()
        else:
            basket = Basket.objects.create(user=user)

        return Response(self.get_serializer(basket).data)

    @action(detail=False, methods=['POST', 'PUT'])
    def book(self, request):
        book_id = request.data.get('book')
        book_count = request.data.get('count', 1)

        if not book_id:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        book = get_object_or_404(Book, id=book_id)

        user = get_user_from_request(request)
        if not user:
            return Response(status=status.HTTP_403_FORBIDDEN)

        if self.request.method == 'POST':
            baskets = Basket.objects.filter(user=user)
            if baskets.exists():
                basket = baskets.last()
            else:
                basket = Basket.objects.create(user=user)

            if basket.book_count + book_count > basket.max_book_count:
                return Response(status=status.HTTP_406_NOT_ACCEPTABLE)

            bookbasket, created = BookBasket.objects.get_or_create(book=book, basket=basket, defaults={'count': book_count})
            if not created:
                bookbasket.count += book_count
                bookbasket.save()

        else: # PUT
            basket_id = request.data.get('basket')
            if not basket_id:
                return Response(status=status.HTTP_400_BAD_REQUEST)
            basket = get_object_or_404(Basket, id=basket_id)
            bookbasket = BookBasket.objects.get(book=book, basket=basket)
            if book_count > 0:
                if basket.book_count - bookbasket.count + book_count > basket.max_book_count:
                    return Response(status=status.HTTP_406_NOT_ACCEPTABLE)
                bookbasket.count = book_count
                bookbasket.save()
            elif book_count == 0:
                bookbasket.delete()
            else:
                return Response(status=status.HTTP_400_BAD_REQUEST)

        return Response(self.get_serializer(basket).data)
