"""화면에 보여 줄 값으로 바꾸는 함수들. DB를 새로 조회하지 않는다(미리 불러온 관계만 쓴다)."""
import html
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Sequence, Tuple

from django.utils.html import escape, strip_tags
from django.utils.safestring import SafeString, mark_safe

# BookAuthor.author_type → 역할 표기. 표기 순서는 지음 · 엮음 · 옮김 · 기획
ROLE_VERB = {1: '지음', 2: '옮김', 3: '기획', 4: '엮음'}
ROLE_ORDER = (1, 4, 2, 3)

STORES = (('aladin', '알라딘'), ('yes24', 'YES24'), ('kyobo', '교보문고'))
STORE_SEARCH_URL = {
    'aladin': 'https://www.aladin.co.kr/search/wsearchresult.aspx?SearchTarget=Book&SearchWord={isbn}',
    # 대문자 /Product/Search 는 메인으로 튕긴다 (2026-09-27 브라우저 확인)
    'yes24': 'https://www.yes24.com/product/search?domain=ALL&query={isbn}',
    'kyobo': 'https://search.kyobobook.co.kr/search?keyword={isbn}&gbCode=TOT&target=total',
}
# 저장된 링크 중 URL.KR 단축 링크는 만료된 것이 있어 믿지 않는다
EXPIRED_SHORTLINK = re.compile(r'^https?://(www\.)?url\.kr/', re.I)

Credit = Sequence[Tuple[str, int]]


def authors_of(book) -> List[Tuple[str, int]]:
    return [(ba.author.name, ba.author_type) for ba in book.authors.all()]


def credit_line(authors: Credit) -> str:
    groups = {}
    for name, role in authors:
        groups.setdefault(role, []).append(name)
    return ' · '.join(f"{', '.join(groups[r])} {ROLE_VERB[r]}" for r in ROLE_ORDER if r in groups)


def card_credit(authors: Credit) -> str:
    for role in ROLE_ORDER:
        names = [n for n, r in authors if r == role]
        if names:
            return names[0] + (' 외' if len(names) > 1 else '')
    return ''


def format_price(won: Optional[int]) -> str:
    return f'{won:,}원' if won else ''


def format_date_ko(d: Optional[date]) -> str:
    return f'{d.year}년 {d.month}월 {d.day}일' if d else ''


def format_month_ko(d: Optional[date]) -> str:
    return f'{d.year}년 {d.month}월' if d else ''


SIZE_RE = re.compile(r'^\s*(\d+)\s*[*xX×]\s*(\d+)\s*$')


def format_size(size: Optional[str]) -> str:
    if not size:
        return ''
    m = SIZE_RE.match(size)
    return f'{m.group(1)}×{m.group(2)}mm' if m else size.strip().replace('*', '×')


def format_isbn(isbn: Optional[str]) -> str:
    return ' '.join((isbn or '').split())


def isbn13(isbn: Optional[str]) -> Optional[str]:
    digits = re.sub(r'\D', '', isbn or '')
    return digits[:13] if len(digits) >= 13 and digits[:3] in ('978', '979') else None


@dataclass(frozen=True)
class StoreLink:
    store: str
    label: str
    url: str


def store_url(book, store: str) -> Optional[str]:
    saved = (getattr(book, f'{store}_url', '') or '').strip()
    if saved and not EXPIRED_SHORTLINK.match(saved):
        return saved
    code = isbn13(book.isbn)
    return STORE_SEARCH_URL[store].format(isbn=code) if code else None


def store_links(book) -> List[StoreLink]:
    links = []
    for store, label in STORES:
        url = store_url(book, store)
        if url:
            links.append(StoreLink(store, label, url))
    return links


def file_url(f) -> str:
    return f.url if f else ''


def cover_card_url(book) -> str:
    return file_url(book.cover_thumbnail) or file_url(book.cover_image)


def cover_url(book) -> str:
    return file_url(book.cover_image)


def cover_3d_url(book) -> str:
    return file_url(book.cover_image_3d) or file_url(book.cover_image)


BOLD = re.compile(r'\*\*(.+?)\*\*')


def strip_marks(text: str) -> str:
    return BOLD.sub(r'\1', text or '')


def short_text(text: str, limit: int) -> str:
    plain = ' '.join(strip_marks(text).split())
    return plain if len(plain) <= limit else plain[:limit - 1].rstrip() + '…'


def render_inline(text: str) -> SafeString:
    """HTML 이스케이프 후 **굵게**만 <strong>으로 (프론트 renderInline과 같은 규칙)."""
    return mark_safe(BOLD.sub(r'<strong>\1</strong>', str(escape(text))))


ZERO_WIDTH = re.compile('[​‌‍⁠﻿]')
HEADING = re.compile(r'^■\s*(.*?)[\s\-–—]*$')
LEAD_MAX = 120


@dataclass
class Section:
    title: Optional[str]
    anchor: str = ''
    lead: Optional[SafeString] = None
    paragraphs: List[SafeString] = field(default_factory=list)
    collapsible: bool = False


def parse_description(text: str) -> List[Section]:
    """'■ 제목' 줄을 구획 제목으로, 빈 줄을 문단 경계로. 첫 구획의 짧은 첫 문단은 리드."""
    sections = [Section(title=None)]
    lines: List[str] = []

    def flush():
        if lines:
            sections[-1].paragraphs.append(mark_safe('<br>'.join(render_inline(l) for l in lines)))
            lines.clear()

    for raw in (text or '').splitlines():
        line = ZERO_WIDTH.sub('', raw).strip()
        heading = HEADING.match(line)
        if heading:
            flush()
            title = heading.group(1).strip() or '소개'
            sections.append(Section(title=title, collapsible='차례' in title))
        elif line:
            lines.append(line)
        else:
            flush()
    flush()

    intro = sections[0]
    if intro.paragraphs and len(html.unescape(strip_tags(intro.paragraphs[0]))) <= LEAD_MAX:
        intro.lead = intro.paragraphs.pop(0)
    sections = [s for s in sections if s.lead or s.paragraphs]
    if len(sections) > 1 and sections[0].title is None:
        sections[0].title = '책 소개'
    for i, s in enumerate(sections, 1):
        s.anchor = f'section-{i}'
    return sections
