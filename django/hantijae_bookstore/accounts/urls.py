from django.urls import include, path
from rest_framework.routers import SimpleRouter
from accounts.views import UserViewSet

app_name = 'accounts'

router = SimpleRouter()
router.register('', UserViewSet, basename='book')

urlpatterns = [
    path('', include((router.urls))),
]
