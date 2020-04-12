from django.contrib import admin
from accounts.models import User, Basket


class UserAdmin(admin.ModelAdmin):
    list_display = ['id', 'username', 'name', 'email', '_notifiable']

    def get_queryset(self, request):
        return super().get_queryset(request).filter(anonymous=False)

    def name(self, user):
        return user.first_name

    def _notifiable(self, user):
        return user.notifiable

    _notifiable.short_description = '소식 받기'
    _notifiable.boolean = True


admin.site.register(User, UserAdmin)
admin.site.register(Basket)