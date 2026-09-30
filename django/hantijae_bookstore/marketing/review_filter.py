"""서평 후보 1차 거르기(코드). 스펙 §4 규칙 1·3과, 2026-09-30 실측으로 조정한 규칙 2:
짧은 제목은 흔한 말과 겹치므로 지은이·한티재·부제·책이라는 단서 가운데 하나가 더 있어야 한다. 남은 것은 LLM이 판별한다."""
import re
from dataclasses import dataclass
from typing import List

from books.models import BookAuthor
from marketing.review_search import normalize_url
from marketing.text import loose_key

SHORT_TITLE = 12   # 글자·숫자 기준 이 길이 이하면 짧은 제목
BOOK_WORDS = ('서평', '리뷰', '독후감', '읽고', '읽었', '읽은', '읽는', '읽기', '완독', '북토크', '북콘서트', '독서',
              '저자', '작가', '출판', '도서', '이 책', '책을', '책은', '책이', '책으로', '후기', '발제', '필사', '북클럽')
EXCLUDE_URL_PARTS = ('blog.naver.com/hantijae_publisher',)   # 한티재 공식 블로그
_BRACKETED = r'[『《〈<「]\s*{}\s*[』》〉>」]'


@dataclass
class BookTerms:
    book: object
    title: str
    key: str
    subtitle_key: str
    author_keys: List[str]
    first_author: str


def _first_author(rows):
    """검색에 붙일 지은이: 번역자가 아닌 첫 사람(없으면 첫 사람)."""
    rows = sorted(rows, key=lambda ba: ba.id)
    main = [ba for ba in rows if ba.author_type != BookAuthor.TRANSLATOR] or rows
    return main[0].author.name if main else ''


def terms(book):
    rows = list(book.authors.all())
    names = [ba.author.name for ba in rows]
    return BookTerms(book, book.title.strip(), loose_key(book.title), loose_key(book.subtitle or ''),
                     [loose_key(n) for n in names if len(loose_key(n)) >= 2], _first_author(rows))


def queries(t):
    """"제목"과 "제목" 지은이. 흔한 말 제목(『내란 앞에서』)은 지은이를 붙여야 책 글이 잡히고, 카카오는 따옴표를 무시한다."""
    base = f'"{t.title}"'
    return [base, f'{base} {t.first_author}'] if t.first_author else [base]


def excluded(post):
    url = normalize_url(post.url)
    return any(p in url for p in EXCLUDE_URL_PARTS)


def mentions_book(post, t):
    text = f'{post.title} {post.snippet}'
    k = loose_key(text)
    if not t.key or t.key not in k:
        return False
    if len(t.key) > SHORT_TITLE or '한티재' in k or any(a in k for a in t.author_keys):
        return True
    if len(t.subtitle_key) >= 4 and t.subtitle_key in k:
        return True
    spaced = r'\s*'.join(map(re.escape, re.sub(r'\s+', '', t.title)))
    if re.search(_BRACKETED.format(spaced), text):
        return True
    return any(w in text for w in BOOK_WORDS)
