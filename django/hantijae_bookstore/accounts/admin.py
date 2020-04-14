from datetime import timedelta
from django.contrib import admin
from django.utils.safestring import mark_safe

from accounts.models import User, Basket


class UserAdmin(admin.ModelAdmin):
    list_display = ['id', 'username', 'name', 'email', '_notifiable', '_created_at', '_last_login']
    fields = ['username', 'first_name', 'email', '_created_at', '_last_login', 'baskets']
    readonly_fields = ['_created_at', '_last_login', 'baskets']

    def get_queryset(self, request):
        return super().get_queryset(request).filter(anonymous=False)

    def name(self, user):
        return user.first_name

    def _notifiable(self, user):
        return user.notifiable

    _notifiable.short_description = '소식 받기'
    _notifiable.boolean = True

    def _created_at(self, user):
        return user.date_joined + timedelta(hours=9)

    def _last_login(self, user):
        if user.last_login:
            return user.last_login + timedelta(hours=9)
        return None

    def baskets(self, user):
        baskets = user.baskets.all()
        result = '<div>'
        for basket in baskets:
            result += f'<a href="/admin/accounts/basket/{basket.id}/">{basket.id}: {basket}</a><br />'
        result += u'</div>'
        return mark_safe(result)


class BasketAdmin(admin.ModelAdmin):
    actions = ['set_ordered', 'set_paid', 'set_sent', 'set_received', 'set_invalid', 'mark_manual']
    list_filter = ['status', 'manual']
    list_display = ['id', 'status', '_user', 'name', 'email', 'phone_number', 'payer', 'receiver_name', 'address',
                    'book_count', 'total_price', '_updated_at']
    fields = ['status', '_user', 'first_name', 'email', 'phone_number', 'payer', 'receiver_first_name', 'address', 'postal_code',
              'book_list', 'book_count', 'max_book_count', 'total_price', 'max_price', '_updated_at']
    readonly_fields = ['_user', 'book_list', 'book_count', 'max_book_count', 'total_price', 'max_price', '_updated_at']
    search_fields = ['first_name', 'email', 'receiver_first_name']

    def _user(self, basket):
        user = basket.user
        if user.anonymous:
            return '비회원'
        return mark_safe(f'<a href="/admin/accounts/user/{user.id}/">{user.username}</a>')

    def name(self, basket):
        return basket.first_name

    def receiver_name(self, basket):
        return basket.receiver_first_name

    def book_list(self, basket):
        book_baskets = basket.books.all()
        result = '<div>'
        for book_basket in book_baskets:
            book = book_basket.book
            result += f'<a href="/admin/books/book/{book.id}/">{book.id}: {book} - {book_basket.count} 권</a><br />'
        result += u'</div>'
        return mark_safe(result)

    def _updated_at(self, basket):
        return basket.updated_at + timedelta(hours=9)

    def set_ordered(self, request, queryset):
        rows_updated = queryset.update(status=Basket.ORDERED)
        self.message_user(request, f"{rows_updated} 개의 책바구니를 '주문 완료' 상태로 만들었습니다.")

    set_ordered.short_description = "'주문 완료' 상태로 만들기"

    def set_paid(self, request, queryset):
        rows_updated = queryset.update(status=Basket.PAID)
        self.message_user(request, f"{rows_updated} 개의 책바구니를 '입금 확인' 상태로 만들었습니다.")

    set_paid.short_description = "'입금 확인' 상태로 만들기"

    def set_sent(self, request, queryset):
        rows_updated = queryset.update(status=Basket.SENT)
        self.message_user(request, f"{rows_updated} 개의 책바구니를 '발송 완료' 상태로 만들었습니다.")

    set_sent.short_description = "'발송 완료' 상태로 만들기"

    def set_received(self, request, queryset):
        rows_updated = queryset.update(status=Basket.RECEIVED)
        self.message_user(request, f"{rows_updated} 개의 책바구니를 '수령 확인' 상태로 만들었습니다.")

    set_received.short_description = "'수령 확인' 상태로 만들기"

    def set_invalid(self, request, queryset):
        rows_updated = queryset.update(status=Basket.INVALID)
        self.message_user(request, f"{rows_updated} 개의 책바구니를 '유효하지 않음' 상태로 만들었습니다.")

    set_invalid.short_description = "'유효하지 않음' 상태로 만들기"

    def mark_manual(self, request, queryset):
        rows_updated = queryset.update(manual=True)
        self.message_user(request, f"{rows_updated} 개의 책바구니를 '직접 입력한 주문'으로 표시했습니다.")

    mark_manual.short_description = "'직접 입력한 주문'으로 표시하기"

admin.site.register(User, UserAdmin)
admin.site.register(Basket, BasketAdmin)
