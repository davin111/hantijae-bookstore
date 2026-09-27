from django.urls import re_path

from web import views

app_name = 'web'

urlpatterns = [
    re_path(r'^$', views.home, name='home'),
    re_path(r'^series=(?P<series_id>\d+)$', views.series_page, name='series'),
    re_path(r'^book=(?P<book_id>\d+)$', views.book_detail, name='book'),
    re_path(r'^search$', views.search_redirect, name='search_redirect'),
    re_path(r'^search=(?P<q>.+)$', views.search_page, name='search'),
    re_path(r'^hantijae$', views.about, name='about'),
    re_path(r'^go/(?P<book_id>\d+)/(?P<store>[a-z0-9]+)$', views.store_redirect, name='go'),
]
