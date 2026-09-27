from django.contrib import admin
from django.db.models import Count

from web.models import Notice, StoreClick


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = ('message', 'state', 'starts_at', 'ends_at', 'created_by')
    list_filter = ('state',)
    fields = ('message', 'link_url', 'link_label', 'starts_at', 'ends_at', 'state')


@admin.register(StoreClick)
class StoreClickAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'book', 'store', 'referrer_host')
    list_filter = ('store', 'created_at')
    search_fields = ('book__title',)
    list_select_related = ('book',)
    change_list_template = 'admin/web/storeclick/change_list.html'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        try:
            qs = response.context_data['cl'].queryset
        except (AttributeError, KeyError):   # 필터 오류 등으로 리다이렉트된 응답
            return response
        labels = dict(StoreClick.STORE_CHOICES)
        response.context_data['by_store'] = [
            {'label': labels.get(r['store'], r['store']), 'n': r['n']}
            for r in qs.order_by().values('store').annotate(n=Count('id')).order_by('-n')]
        response.context_data['by_book'] = qs.order_by().values('book__title').annotate(n=Count('id')).order_by('-n')[:20]
        return response
