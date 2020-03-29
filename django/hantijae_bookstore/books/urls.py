from django.urls import include, path
from rest_framework.routers import SimpleRouter
from books.views import BookViewSet

app_name = 'books'

router = SimpleRouter()
router.register('', BookViewSet, basename='book')

urlpatterns = [
    path('', include((router.urls))),
]
