from django.db import models
from django.contrib.auth.models import User

from books.models import Book
from core.models import BaseModel

class Basket(BaseModel):
    NONE = 1
    ORDERED = 2
    PAID = 3
    COMPLETED = 4

    BASKET_STATUS = (
        (NONE, 'none'),
        (ORDERED, 'ordered'),
        (PAID, 'paid'),
        (COMPLETED, 'completed'),
    )

    user = models.ForeignKey(User, related_name='baskets', on_delete=models.CASCADE)
    max_book_count = models.PositiveSmallIntegerField(default=10)
    status = models.IntegerField(choices=BASKET_STATUS, default=NONE)
    price = models.PositiveSmallIntegerField(default=100000)

    class Meta:
        db_table = 'accounts_basket'

    def __str__(self):
        return f'{self.user.username} - Basket {self.id}'


class BookBasket(BaseModel):
    basket = models.ForeignKey(Basket, related_name='books', on_delete=models.CASCADE)
    book = models.ForeignKey(Book, related_name='baskets', on_delete=models.CASCADE)
    count = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = 'accounts_bookbasket'

    def __str__(self):
        return f'{self.basket.id} - {self.book.title}'
