from django.contrib import admin

from marketing.models import (BookProfile, Briefing, CopyNote, Draft, DraftMessage, FundingSnapshot, HookDate,
                              Proposal, SalesSnapshot, Signal, SignalEvidence, WatchQuery)


@admin.register(SalesSnapshot)
class SalesSnapshotAdmin(admin.ModelAdmin):
    list_display = ('date', 'book', 'sales_point', 'short_reviews', 'reviews')
    list_filter = ('date',)
    search_fields = ('book__title',)


@admin.register(HookDate)
class HookDateAdmin(admin.ModelAdmin):
    list_display = ('name', 'month', 'day', 'year', 'memorial')
    filter_horizontal = ('books',)


@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'kind', 'book', 'headline', 'status', 'sent_at')
    list_filter = ('kind', 'status')


@admin.register(Draft)
class DraftAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'proposal', 'channel', 'version', 'status', 'posted_at')
    list_filter = ('channel', 'status')


class SignalEvidenceInline(admin.TabularInline):
    model = SignalEvidence
    raw_id_fields = ('entry',)
    extra = 0


@admin.register(Signal)
class SignalAdmin(admin.ModelAdmin):
    list_display = ('found_at', 'kind', 'book', 'title', 'happens_on', 'relevant', 'sensitive', 'used_at')
    list_filter = ('kind', 'relevant', 'sensitive')
    search_fields = ('title',)
    inlines = (SignalEvidenceInline,)


for model in (BookProfile, Briefing, CopyNote, DraftMessage, FundingSnapshot, WatchQuery):
    admin.site.register(model)
