from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from books.models import Book, Category, Series
from books.serializers import (BookSerializer, CategorySerializer, SeriesSerializer,
                               SimpleBookSerializer, SimpleSeriesSerializer)


class BookViewSet(viewsets.GenericViewSet):
    queryset = Book.objects.all()
    serializer_class = BookSerializer

    def get_serializer_class(self):
        if self.action == 'list':
            return SimpleBookSerializer
        return self.serializer_class

    def list(self, request):
        search_word = request.query_params.get('search')
        if search_word:
            search_word = search_word.strip()
            searched_titles = self.get_queryset().filter(
                Q(title__icontains=search_word) | Q(subtitle__icontains=search_word)).values_list('id', flat=True)
            searched_authors = self.get_queryset().filter(
                authors__author__name__icontains=search_word
            ).values_list('id', flat=True)
            queryset = Book.objects.filter(Q(id__in=searched_titles) | Q(id__in=searched_authors))
        else:
            queryset = self.get_queryset()
        return Response(self.get_serializer(queryset, many=True).data)

    def retrieve(self, request, pk=None):
        book = get_object_or_404(Book, pk=pk)
        return Response(self.get_serializer(book).data)

    @action(detail=False, methods=["GET"])
    def count(self, request):
        book_count = cache.get("book_count")
        if book_count is None:
            book_count = self.get_queryset().count()
            cache.set("book_count", book_count, 3600)
        return Response({"count": book_count})


class CategoryViewSet(viewsets.GenericViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    def list(self, request):
        queryset = self.get_queryset()
        return Response(self.get_serializer(queryset, many=True).data)


class SeriesViewSet(viewsets.GenericViewSet):
    queryset = Series.objects.all()
    serializer_class = SimpleSeriesSerializer

    def get_serializer_class(self):
        if self.action == "retrieve":
            return SeriesSerializer
        return self.serializer_class

    def list(self, request):
        data = cache.get("series")
        if data is None:
            queryset = self.get_queryset()
            fixed_tuple = ("단행본", "교양문고", "산문선", "시선", "팸플릿")
            data = []
            for name in fixed_tuple:
                try:
                    series = queryset.get(name=name)
                    data.append(self.get_serializer(series).data)
                except ObjectDoesNotExist:
                    pass
            cache.set("series", data, 3600)
        return Response(data)

    def retrieve(self, request, pk=None):
        series = get_object_or_404(Series, pk=pk)
        data = cache.get(f"series_{pk}")
        if data is None:
            data = self.get_serializer(series).data
            cache.set(f"series_{pk}", data, 3600)
        return Response(data)
