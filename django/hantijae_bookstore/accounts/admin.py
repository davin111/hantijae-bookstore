from django.contrib import admin
from accounts.models import User, Basket


admin.site.register(User)
admin.site.register(Basket)


# class UserAdmin(admin.ModelAdmin):
#     list_display = ['id', 'first_name', ]