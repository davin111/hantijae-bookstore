from django import template

from web import presenters

register = template.Library()


@register.filter
def credit(book):
    return presenters.credit_line(presenters.authors_of(book))


@register.filter
def card_credit(book):
    return presenters.card_credit(presenters.authors_of(book))


@register.filter
def cover_card_url(book):
    return presenters.cover_card_url(book)


@register.filter
def cover_url(book):
    return presenters.cover_url(book)


@register.filter
def cover_3d_url(book):
    return presenters.cover_3d_url(book)


@register.filter
def date_ko(d):
    return presenters.format_date_ko(d)


@register.filter
def month_ko(d):
    return presenters.format_month_ko(d)
