from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from books.models import Book, Category, Author, Series
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
        if self.action == 'retrieve':
            return SeriesSerializer
        return self.serializer_class

    def list(self, request):
        queryset = self.get_queryset()
        fixed_tuple = ("단행본", "한티재 교양문고", "한티재 산문선", "한티재 시선", "한티재 팸플릿")
        data = []
        for name in fixed_tuple:
            try:
                series = queryset.get(name=name)
                data.append(self.get_serializer(series).data)
            except ObjectDoesNotExist:
                pass

        return Response(data)

    def retrieve(self, request, pk=None):
        series = get_object_or_404(Series, pk=pk)
        return Response(self.get_serializer(series).data)
