from urllib.parse import quote

from django.conf import settings
from django.core import signing

SALT = 'book-preview'
MAX_AGE_SECONDS = 60 * 60 * 24 * 30


def make_preview_token(book_id: int) -> str:
    return signing.TimestampSigner(salt=SALT).sign(str(book_id))


def is_valid_preview_token(book_id: int, token: str) -> bool:
    if not token:
        return False
    try:
        value = signing.TimestampSigner(salt=SALT).unsign(token, max_age=MAX_AGE_SECONDS)
    except signing.BadSignature:  # SignatureExpired 포함
        return False
    return value == str(book_id)


def preview_url(book_id: int) -> str:
    return f"{settings.SITE_URL}/book={book_id}?preview={quote(make_preview_token(book_id))}"
