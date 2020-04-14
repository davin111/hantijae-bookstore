from django.db import models
from django.db.models import Sum
from django.conf import settings
from django.contrib.auth.models import User, AbstractUser
from django.contrib.sessions.models import Session

from books.models import Book
from core.models import BaseModel

class Basket(BaseModel):
    INVALID = -1
    NONE = 1
    ORDERED = 2
    PAID = 3
    SENT = 4
    RECEIVED = 5

    BASKET_STATUS = (
        (INVALID, '유효하지 않음'),
        (NONE, '책 담는 중'),
        (ORDERED, '주문 완료'),
        (PAID, '입금 확인'),
        (SENT, '발송 완료'),
        (RECEIVED, '수령 확인')
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='baskets', on_delete=models.CASCADE)
    max_book_count = models.PositiveSmallIntegerField(default=10)
    max_price = models.PositiveIntegerField(default=100000)
    status = models.IntegerField(choices=BASKET_STATUS, default=NONE)
    manual = models.BooleanField(default=False, help_text="직접 입력한 주문")

    last_name = models.CharField(max_length=300, blank=True)
    first_name = models.CharField(max_length=300, blank=True)
    email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=150, blank=True)
    receiver_last_name = models.CharField(max_length=300, blank=True)
    receiver_first_name = models.CharField(max_length=300, blank=True)
    address = models.CharField(max_length=3000, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    payer = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = 'accounts_basket'

    def __str__(self):
        return f'{self.user.username} - Basket {self.id}'

    @property
    def book_count(self):
        return self.books.aggregate(book_count=Sum('count'))['book_count'] or 0

    @property
    def total_price(self):
        total_price = 0
        for book_basket in self.books.all():
            total_price += (book_basket.count * book_basket.book.full_price)
        return total_price


class MaxBookCountException(Exception):
    pass


class BookBasket(BaseModel):
    basket = models.ForeignKey(Basket, related_name='books', on_delete=models.CASCADE)
    book = models.ForeignKey(Book, related_name='baskets', on_delete=models.CASCADE)
    count = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = 'accounts_bookbasket'

    def __str__(self):
        return f'{self.basket.id} - {self.book.title}'


class User(AbstractUser):
    last_session = models.OneToOneField(Session, null=True, blank=True, on_delete=models.SET_NULL)
    anonymous = models.BooleanField(default=False)
    notifiable = models.BooleanField(default=False)

    class Meta:
        db_table = 'accounts_user'
    
    def __str__(self):
        return self.username
