"""LLM 추출값 → Book 필드. 값 정규화와 검수 경고 계산."""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from django.utils import timezone

from books.models import Book, BookAuthor
from intake.extract import QUALITY_THRESHOLD, is_verbatim

ROLE_TO_TYPE = {'지은이': BookAuthor.NORMAL, '저자': BookAuthor.NORMAL, '글': BookAuthor.NORMAL,
                '옮긴이': BookAuthor.TRANSLATOR, '번역': BookAuthor.TRANSLATOR, '역자': BookAuthor.TRANSLATOR,
                '기획': BookAuthor.PLANNER, '엮은이': BookAuthor.COMPILER, '엮음': BookAuthor.COMPILER}
TYPE_TO_ROLE = {BookAuthor.NORMAL: '지은이', BookAuthor.TRANSLATOR: '옮긴이',
                BookAuthor.PLANNER: '기획', BookAuthor.COMPILER: '엮은이'}
REQUIRED = ('title', 'authors', 'isbn', 'published_date', 'page_count', 'full_price', 'category')
FIELD_LABELS = {'title': '제목', 'subtitle': '부제', 'authors': '저자', 'isbn': 'ISBN', 'published_date': '발행일',
                'page_count': '쪽수', 'full_price': '가격', 'category': '분야', 'size': '판형', 'series': '시리즈',
                'series_number': '시리즈 번호', 'short_description': '요약 소개', 'description': '책 소개'}
MAX_PRICE = 65535  # MySQL SMALLINT UNSIGNED (PositiveSmallIntegerField)


def warning(code, message, blocking=False, audience='family'):
    return {'code': code, 'message': message, 'blocking': blocking, 'audience': audience}


def normalize_size(value) -> Optional[str]:
    m = re.search(r'(\d{2,3})\s*[×xX*＊]\s*(\d{2,3})', str(value or ''))
    return f'{m.group(1)}*{m.group(2)}' if m else None


def isbn_digits(value) -> str:
    digits = re.sub(r'\D', '', str(value or ''))
    return digits[:13] if digits[:3] in ('978', '979') else digits


def isbn13_valid(digits) -> bool:
    if not re.fullmatch(r'97[89]\d{10}', digits or ''):
        return False
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:12]))
    return (10 - total % 10) % 10 == int(digits[12])


def format_isbn(value) -> Optional[str]:
    """보도자료 표기(979-11-92455-87-7)를 살리고 부가기호는 뗀다."""
    s = str(value or '').strip()
    m = re.match(r'97[89][\d-]{9,15}\d', s)
    if m and isbn13_valid(isbn_digits(m.group(0))) and len(isbn_digits(m.group(0))) == 13:
        return m.group(0)
    d = isbn_digits(s)
    return d if isbn13_valid(d) else None


def to_int(value) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    digits = re.sub(r'\D', '', str(value or ''))
    return int(digits) if digits else None


def parse_date(value) -> Optional[date]:
    if isinstance(value, date):
        return value
    m = re.search(r'(\d{4})\D+(\d{1,2})\D+(\d{1,2})', str(value or ''))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def normalize_key(s) -> str:
    s = unicodedata.normalize('NFC', str(s or '')).replace('한티재', '')
    return re.sub(r'[\s\W_]+', '', s)


def match_name(name, table: Dict[str, int]) -> Optional[int]:
    key = normalize_key(name)
    if not key:
        return None
    return next((pk for n, pk in table.items() if normalize_key(n) == key), None)


def aladin_search_url(isbn) -> str:
    return f'https://www.aladin.co.kr/search/wsearchresult.aspx?SearchWord={isbn_digits(isbn)}'


@dataclass
class Normalized:
    fields: dict
    authors: List[Tuple[str, int]]
    series_id: Optional[int]
    series_index: Optional[str]
    isbn_addon: str
    unresolved: List[str] = field(default_factory=list)
    notes: List[dict] = field(default_factory=list)


def normalize_extraction(data, categories, series) -> Normalized:
    authors = []
    for a in data.get('authors') or []:
        if isinstance(a, dict) and (a.get('name') or '').strip():
            authors.append((a['name'].strip(), ROLE_TO_TYPE.get((a.get('role') or '').strip(), BookAuthor.NORMAL)))
    isbn = format_isbn(data.get('isbn'))
    price = to_int(data.get('price'))
    if price is not None and not 0 < price <= MAX_PRICE:
        price = None
    fields = {
        'title': (data.get('title') or '').strip(),
        'subtitle': (data.get('subtitle') or '').strip(),
        'short_description': (data.get('short_description') or '').strip(),
        'description': (data.get('description') or '').strip(),
        'full_price': price,
        'page_count': to_int(data.get('page_count')),
        'size': normalize_size(data.get('size')),
        'isbn': isbn,
        'published_date': parse_date(data.get('published_date')),
        'category_id': categories.get(data.get('category') or '') or match_name(data.get('category'), categories),
        'aladin_url': aladin_search_url(isbn) if isbn else '',
    }
    unresolved = [k for k in REQUIRED
                  if not (authors if k == 'authors' else fields['category_id' if k == 'category' else k])]
    notes = []
    series_id = match_name(data.get('series'), series) if data.get('series') else None
    if data.get('series') and series_id is None:
        notes.append(warning('series_unknown', f"시리즈 '{data['series']}'를 사이트에서 못 찾아 단행본으로 넣었어요",
                             audience='admin'))
    index = str(data.get('series_number')).strip() if data.get('series_number') else None
    return Normalized(fields, authors, series_id, index or None, str(data.get('isbn_addon') or ''), unresolved, notes)


def find_isbn_duplicate(isbn, exclude_pk=None) -> Optional[int]:
    """표기(하이픈 유무·부가기호)와 무관하게 숫자로 비교한 같은 ISBN의 다른 책 ID."""
    digits = isbn_digits(isbn)
    if not digits:
        return None
    rows = Book.objects.exclude(isbn__isnull=True).exclude(pk=exclude_pk).only('id', 'isbn')
    return next((b.id for b in rows if isbn_digits(b.isbn) == digits), None)


def check_book(book, unresolved, edited, source_text, source_quality) -> List[dict]:
    ws = [warning(f'missing:{k}', f'{FIELD_LABELS[k]}을(를) 보도자료에서 찾지 못했어요 — 답장으로 알려 주세요', True)
          for k in REQUIRED if k in unresolved]
    digits = isbn_digits(book.isbn)
    if book.isbn and not isbn13_valid(digits):
        ws.append(warning('isbn_invalid', f'ISBN {book.isbn}이(가) 올바르지 않아요', True))
    elif digits:
        dup = find_isbn_duplicate(book.isbn, exclude_pk=book.pk)
        if dup:
            ws.append(warning('isbn_duplicate', f'이미 사이트에 있는 ISBN이에요 (책 #{dup})', True))
    if not book.cover_image:
        ws.append(warning('no_front_cover', '앞표지 이미지가 없어요 — 이 메시지에 사진으로 답장해 주세요', True))
    if not book.cover_image_3d:
        ws.append(warning('no_3d', '입체 표지 이미지가 없어요'))
    if book.full_price and not 1000 <= book.full_price <= MAX_PRICE:
        ws.append(warning('price_range', f'가격 {book.full_price:,}원이 맞는지 확인해 주세요'))
    if book.page_count and not 16 <= book.page_count <= 2000:
        ws.append(warning('page_range', f'쪽수 {book.page_count}쪽이 맞는지 확인해 주세요'))
    today = timezone.localdate()
    if book.published_date and not date(2000, 1, 1) <= book.published_date <= today + timedelta(days=366):
        ws.append(warning('date_range', f'발행일 {book.published_date}이(가) 맞는지 확인해 주세요'))
    if not book.size:
        ws.append(warning('size_missing', '판형을 찾지 못했어요'))
    if source_quality >= QUALITY_THRESHOLD:
        for f, label in (('short_description', '요약 소개'), ('description', '책 소개')):
            value = getattr(book, f)
            if f not in edited and value and not is_verbatim(value, source_text):
                ws.append(warning(f'verbatim:{f}', f'{label}가 보도자료 원문과 달라요 — 미리보기에서 확인해 주세요'))
    else:
        ws.append(warning('verbatim_unchecked', '원문 추출 품질이 낮아 소개글 원문 대조를 못 했어요', audience='admin'))
    return ws
