import re

from intake.mapping import isbn_digits, normalize_extraction, normalize_key

EVAL_FIELDS = ('title', 'subtitle', 'authors', 'size', 'page_count', 'full_price', 'isbn', 'published_date', 'series')


def _series_key(v):
    m = re.match(r'(.*?)(\d+)?$', normalize_key(v or ''))
    return (m.group(1), int(m.group(2)) if m.group(2) else None)


def expected_from_book(book):
    bs = book.series.select_related('series').first()
    return {'title': book.title, 'subtitle': book.subtitle,
            'authors': sorted(ba.author.name for ba in book.authors.select_related('author')),
            'size': book.size, 'page_count': book.page_count, 'full_price': book.full_price, 'isbn': book.isbn,
            'published_date': book.published_date.isoformat(),
            'series': f'{bs.series.name} {bs.index or ""}'.strip() if bs else ''}


def actual_from_data(data, categories, series):
    n = normalize_extraction(data, categories, series)
    f = n.fields
    return {'title': f['title'], 'subtitle': f['subtitle'], 'authors': sorted(a for a, _ in n.authors),
            'size': f['size'], 'page_count': f['page_count'], 'full_price': f['full_price'], 'isbn': f['isbn'],
            'published_date': f['published_date'].isoformat() if f['published_date'] else None,
            'series': f"{data.get('series') or '단행본'} {data.get('series_number') or ''}".strip()}


def compare(expected, actual):
    out = {}
    for k in EVAL_FIELDS:
        e, a = expected.get(k), actual.get(k)
        if k == 'isbn':
            out[k] = isbn_digits(e) == isbn_digits(a)
        elif k in ('title', 'subtitle'):
            out[k] = normalize_key(e) == normalize_key(a)
        elif k == 'series':
            out[k] = _series_key(e) == _series_key(a)
        else:
            out[k] = e == a
    return out
