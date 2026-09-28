from django.contrib import admin

from context.models import ContextEntry, Participant


@admin.register(ContextEntry)
class ContextEntryAdmin(admin.ModelAdmin):
    """읽기 전용. 지우기만 된다(운영진이 개발자에게 부탁한 경우)."""
    list_display = ['at', 'role', 'author_name', 'short_text', 'media', 'origin']
    list_filter = ['role', 'origin', 'media']
    search_fields = ['text']
    date_hierarchy = 'at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='본문')
    def short_text(self, obj):
        return obj.text[:60]


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ['role', 'telegram_user_id', 'aliases']
