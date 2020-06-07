from django.contrib.auth import authenticate, login, logout
from django.contrib.sessions.models import Session
from django.db import IntegrityError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User, Basket, BookBasket, MaxBookCountException
from accounts.serializers import UserSerializer, BasketSerializer, OrderSerializer
from accounts.utils import get_user_from_request
from books.models import Book

class UserViewSet(viewsets.GenericViewSet):
    serializer_class = UserSerializer

    def create(self, request, *args, **kwargs):
        username = request.data.get('username')
        email = request.data.get('email')
        password = request.data.get('password')
        last_name = request.data.get('family_name')
        first_name = request.data.get('given_name')
        notifiable = request.data.get('notifiable')
        if not (username and email and password and last_name is not None and first_name and notifiable is not None):
            return Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.create_user(username, email, password)
        except IntegrityError:
            return Response(status=status.HTTP_406_NOT_ACCEPTABLE)
        user.last_name = last_name
        user.first_name = first_name
        user.notifiable = notifiable
        user.save()

        login(request, user)
        session_key = request.session.session_key
        try:
            user.last_session = Session.objects.get(pk=session_key)
            user.save()
            #print("session saved")
        except Session.DoesNotExist:
            pass
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['PUT'])
    def login(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        try:
            User.objects.get(username=username)
        except User.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            session_key = request.session.session_key
            try:
                user.last_session = Session.objects.get(pk=session_key)
                user.save()
                #print("session saved")
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

    def get_serializer_class(self):
        if self.action == 'order' and self.request.method == 'GET':
            return OrderSerializer
        return self.serializer_class

    def list(self, request):
        user = get_user_from_request(request)
        if not user:
            return Response(status=status.HTTP_403_FORBIDDEN)

        info = request.query_params.get('info', '2020.04.10YEARS')

        baskets = Basket.objects.filter(user=user, status=Basket.NONE, info=info)
        if baskets.exists():
            basket = baskets.last()
        else:
            basket = Basket.objects.create(user=user, info=info)

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

        info = request.query_params.get('info', '2020.04.10YEARS')

        if self.request.method == 'POST':
            baskets = Basket.objects.filter(user=user, status=Basket.NONE, info=info)
            if baskets.exists():
                basket = baskets.last()
            else:
                basket = Basket.objects.create(user=user, info=info)

            if basket.book_count + book_count > basket.max_book_count:
                return Response(status=status.HTTP_406_NOT_ACCEPTABLE)

            bookbasket, created = BookBasket.objects.get_or_create(book=book, basket=basket, defaults={'count': book_count})
            if not created:
                bookbasket.count += book_count
                bookbasket.save()

        else:  # PUT
            basket_id = request.data.get('basket')
            if not basket_id:
                return Response(status=status.HTTP_400_BAD_REQUEST)
            basket = get_object_or_404(Basket, id=basket_id)
            if basket.status != Basket.NONE:
                return Response(status=status.HTTP_406_NOT_ACCEPTABLE)
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

    @action(detail=False, methods=['GET', 'PUT'])
    def order(self, request):
        info = request.query_params.get('info', '2020.04.10YEARS')

        if self.request.method == 'GET':
            user = get_user_from_request(request)
            if not user:
                return Response(status=status.HTTP_403_FORBIDDEN)
            baskets = Basket.objects.filter(Q(user=user) & ~Q(status=Basket.NONE)).order_by('-id')
            return Response(self.get_serializer(baskets, many=True).data)


        else:  # PUT
            basket_id = request.data.get('basket')
            basket = get_object_or_404(Basket, id=basket_id)
            if basket.status != Basket.NONE:
                return Response(status=status.HTTP_406_NOT_ACCEPTABLE)

            email = request.data.get('email')
            phone_number = request.data.get('phone_number')
            payer = request.data.get('payer')

            if info == '2020.06.NEWBOOK':
                name = request.data.get('name')
                addresses = request.data.get('addresses')
                signs = request.data.get('signs')

                if basket.books.count() > 1 or basket.books.exclude(book_id=110).exists():
                    return Response(status=status.HTTP_400_BAD_REQUEST)

                book_count = basket.books.last().count
                if (not (basket_id and name and email and phone_number and addresses and signs and payer)
                    or book_count != len(addresses) or book_count != len(signs)):
                    return Response(status=status.HTTP_400_BAD_REQUEST)

                basket.books.all().delete()
                basket.first_name = name
                basket.email = email
                basket.phone_number = phone_number
                basket.payer = payer
                basket.status = Basket.ORDERED
                basket.save()

                book_basket_list = [BookBasket(basket=basket, book_id=110, address=addresses[str(i)], sign=signs[str(i)]) for i in range(book_count)]
                BookBasket.objects.bulk_create(book_basket_list)
                return Response(self.get_serializer(basket).data)


            last_name = request.data.get('family_name')
            first_name = request.data.get('given_name')
            receiver_last_name = request.data.get('receiver_family_name')
            receiver_first_name = request.data.get('receiver_given_name')
            address = request.data.get('address')
            postal_code = request.data.get('postal_code')
            if not (basket_id and last_name and first_name and email and phone_number
                    and receiver_last_name and receiver_first_name and address and payer):
                return Response(status=status.HTTP_400_BAD_REQUEST)

            basket.last_name = last_name
            basket.first_name = first_name
            basket.email = email
            basket.phone_number = phone_number
            basket.receiver_last_name = receiver_last_name
            basket.receiver_first_name = receiver_first_name
            basket.address = address
            basket.postal_code = postal_code
            basket.payer = payer
            basket.status = Basket.ORDERED
            basket.save()
            return Response(self.get_serializer(basket).data)
