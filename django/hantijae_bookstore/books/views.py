from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from books.models import Book, Category, Author, Series
from books.serializers import BookSerializer, CategorySerializer, SeriesSerializer

class BookViewSet(viewsets.GenericViewSet):
    queryset = Book.objects.all()
    serializer_class = BookSerializer

    def list(self, request):
        queryset = self.get_queryset()
        return Response(self.get_serializer(queryset, many=True).data)

    def retrieve(self, request, pk=None):
        book = get_object_or_404(Book, pk=pk)
        return Response(self.get_serializer(book).data)


class CategoryViewSet(viewsets.GenericViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    def list(self, request):
        queryset = self.get_queryset()
        return Response(self.get_serializer(queryset, many=True).data)


class SeriesViewSet(viewsets.GenericViewSet):
    queryset = Series.objects.all()
    serializer_class = SeriesSerializer

    def list(self, request):
        queryset = self.get_queryset()
        data = self.get_serializer(queryset, many=True).data
        
        include_normal = request.query_params.get('include_normal')
        if include_normal:
            normal_books = Book.objects.filter(series__isnull=True)
            normal = {
                "id": None,
                "name": "단행본",
                "books": BookSerializer(normal_books, many=True).data
            }
            data.append(normal)
        return Response(data)
