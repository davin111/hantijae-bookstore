from django.contrib import admin

from web.models import Notice


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = ('message', 'state', 'starts_at', 'ends_at', 'created_by')
    list_filter = ('state',)
    fields = ('message', 'link_url', 'link_label', 'starts_at', 'ends_at', 'state')
