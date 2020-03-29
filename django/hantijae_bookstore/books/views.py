from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from books.models import Book, Category, Author
from books.serializers import BookSerializer, CategorySerializer

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
