from django.contrib import admin

from intake.models import BookDraft, DraftRevision, IntakeSource, PendingPatch, TelegramChat, WorkerState


@admin.register(IntakeSource)
class IntakeSourceAdmin(admin.ModelAdmin):
    list_display = ['id', 'kind', 'title', 'status', 'stable_since', 'updated_at']
    list_filter = ['kind', 'status']
    search_fields = ['title', 'drive_folder_id']


@admin.register(BookDraft)
class BookDraftAdmin(admin.ModelAdmin):
    list_display = ['id', 'book', 'state', 'version', 'updated_at']
    list_filter = ['state']


admin.site.register(DraftRevision)
admin.site.register(PendingPatch)
admin.site.register(TelegramChat)
admin.site.register(WorkerState)
