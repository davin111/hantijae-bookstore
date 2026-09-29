"""선정 목록 글자에서 한티재 책을 찾는다. ISBN이 가장 확실하고, 없으면 제목 + (저자 이름 또는 '한티재')."""
import re
from dataclasses import dataclass
from typing import List

from books.models import Book
from marketing.text import title_key

MIN_TITLE_KEY = 4   # '시월'처럼 짧은 제목은 남의 긴 제목 안에 흔히 들어 있어 제목 대조를 하지 않는다


def isbn13(raw):
    """'978-89-964413-1-1  03810'처럼 부가기호가 붙은 값에서 앞의 13자리만."""
    m = re.match(r'[\d\-]+', (raw or '').strip())
    digits = re.sub(r'\D', '', m.group(0)) if m else ''
    return digits if len(digits) == 13 else ''


@dataclass
class Hit:
    book: Book
    how: str  # 'isbn' | 'title'


def our_books():
    return list(Book.objects.filter(is_published=True).prefetch_related('authors__author'))


def match_books(texts, books) -> List[Hit]:
    blob = '\n'.join(t for t in texts if t)
    digits = re.sub(r'[\s\-]', '', blob)   # PDF가 ISBN 중간에서 줄을 바꾸거나 하이픈을 넣어도 찾게
    flat = title_key(blob)
    hits = []
    for book in books:
        isbn = isbn13(book.isbn)
        if isbn and isbn in digits:
            hits.append(Hit(book, 'isbn'))
            continue
        key = title_key(book.title)
        if len(key) < MIN_TITLE_KEY or key not in flat:
            continue
        names = [title_key(ba.author.name) for ba in book.authors.all()]
        if '한티재' in flat or any(n and n in flat for n in names):
            hits.append(Hit(book, 'title'))
    return hits
