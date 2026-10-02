from django.contrib.sitemaps.views import sitemap
from django.urls import re_path

from web import views
from web.sitemaps import SITEMAPS

app_name = 'web'

urlpatterns = [
    re_path(r'^$', views.home, name='home'),
    re_path(r'^books$', views.all_books, name='all_books'),
    re_path(r'^series=(?P<series_id>\d+)$', views.series_page, name='series'),
    re_path(r'^book=(?P<book_id>\d+)$', views.book_detail, name='book'),
    re_path(r'^search$', views.search_redirect, name='search_redirect'),
    re_path(r'^search=(?P<q>.+)$', views.search_page, name='search'),
    re_path(r'^hantijae$', views.about, name='about'),
    re_path(r'^go/(?P<book_id>\d+)/(?P<store>[a-z0-9_]+)$', views.store_redirect, name='go'),
    re_path(r'^sitemap\.xml$', sitemap, {'sitemaps': SITEMAPS}, name='sitemap'),
    re_path(r'^robots\.txt$', views.robots_txt, name='robots'),
]
