from django.urls import include, path
from rest_framework.routers import SimpleRouter
from accounts.views import UserViewSet, BasketViewSet

app_name = 'accounts'

router = SimpleRouter()
router.register('basket', BasketViewSet, basename='basket')
router.register('', UserViewSet, basename='user')

urlpatterns = [
    path('', include((router.urls))),
]
