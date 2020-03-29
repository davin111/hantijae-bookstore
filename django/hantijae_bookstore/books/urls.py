from django.urls import include, path
from rest_framework.routers import SimpleRouter
from books.views import BookViewSet, CategoryViewSet

app_name = 'books'

router = SimpleRouter()
router.register('category', CategoryViewSet, basename='category')
router.register('', BookViewSet, basename='book')

urlpatterns = [
    path('', include((router.urls))),
]
