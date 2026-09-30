from django.contrib import admin

from context.models import FORGET_FIELDS, ContextEntry, Participant


@admin.register(ContextEntry)
class ContextEntryAdmin(admin.ModelAdmin):
    """읽기 전용. 운영진이 개발자에게 지워 달라고 하면 삭제 대신 '잊기' 동작을 쓴다(가져오기를 다시 해도 안 살아남)."""
    list_display = ['at', 'source', 'role', 'author_name', 'short_text', 'media', 'origin', 'forgotten']
    list_filter = ['source', 'role', 'origin', 'media', 'forgotten']
    actions = ['forget_selected']
    search_fields = ['text', 'media_text', 'heading', 'link_text']
    date_hierarchy = 'at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.action(description='선택한 기록 잊기(내용 비움, 다시 가져와도 되살아나지 않음)')
    def forget_selected(self, request, queryset):
        queryset.update(**FORGET_FIELDS)

    @admin.display(description='본문')
    def short_text(self, obj):
        return (obj.heading + ' ' if obj.heading else '') + (obj.text or obj.media_text)[:60]


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ['role', 'telegram_user_id', 'aliases']
