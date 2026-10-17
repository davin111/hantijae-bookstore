from django.contrib import admin

from visuals.models import ApprovedImage, CardJob


@admin.register(CardJob)
class CardJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'draft', 'state', 'chat_id', 'created_at', 'completed_at')
    list_filter = ('state',)
    readonly_fields = ('draft', 'chat_id', 'reply_to', 'fingerprint', 'state', 'attempts', 'started_at',
                       'completed_at', 'illustration_at', 'plan', 'files', 'receipt', 'error')

    def has_add_permission(self, request):
        return False


@admin.register(ApprovedImage)
class ApprovedImageAdmin(admin.ModelAdmin):
    list_display = ('book', 'kind', 'label', 'active')
    list_filter = ('kind', 'active')
