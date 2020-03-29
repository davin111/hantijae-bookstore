from django.urls import include, path
from rest_framework.routers import SimpleRouter
from books.views import BookViewSet, CategoryViewSet, SeriesViewSet

app_name = 'books'

router = SimpleRouter()
router.register('category', CategoryViewSet, basename='category')
router.register('series', SeriesViewSet, basename='series')
router.register('', BookViewSet, basename='book')

urlpatterns = [
    path('', include((router.urls))),
]
