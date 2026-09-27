from django.urls import re_path

from web import views

app_name = 'web'

urlpatterns = [
    re_path(r'^go/(?P<book_id>\d+)/(?P<store>[a-z0-9]+)$', views.store_redirect, name='go'),
]
