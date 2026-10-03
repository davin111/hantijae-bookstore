from django.urls import path

from ops import views

app_name = 'ops'

urlpatterns = [
    path('status', views.status, name='status'),
]
