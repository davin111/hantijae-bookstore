"""화면에 보여 줄 값으로 바꾸는 함수들. DB를 새로 조회하지 않는다(미리 불러온 관계만 쓴다)."""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Sequence, Tuple

from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

from books.constants import SERIES_MENU_NAME, SERIES_NUMBER_DIGITS, SERIES_OFFICIAL_NAME

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
# 전자책 서점. 키는 /go/ 주소와 클릭 기록(StoreClick.store)에 그대로 쓴다
EBOOK_STORES = (('e_aladin', '알라딘'), ('e_yes24', 'YES24'), ('e_kyobo', '교보문고'), ('ridi', '리디'))
EBOOK_FIELD = {'e_aladin': 'ebook_aladin_url', 'e_yes24': 'ebook_yes24_url', 'e_kyobo': 'ebook_kyobo_url',
               'ridi': 'ebook_ridi_url'}
# 전자책 ISBN 검색이 상품까지 닿는 곳만(2026-10-02 확인). 예스24 검색은 쿠키 없는 데스크톱 첫 방문자를 첫 화면으로
# 보내고, 리디 검색 화면은 스크립트로 그려서 확인할 수 없다 → 이 둘은 저장한 상품 주소가 있을 때만 보인다.
EBOOK_SEARCH_URL = {
    'e_aladin': 'https://www.aladin.co.kr/search/wsearchresult.aspx?SearchTarget=eBook&SearchWord={isbn}',
    'e_kyobo': 'https://search.kyobobook.co.kr/search?keyword={isbn}&gbCode=TOT&target=total',
}
# 제3자 단축 링크는 믿지 않는다(2026-09-29 확인): bit.ly 는 브라우저에 7초 미리보기 페이지를 끼우고,
# url.kr 은 만료됐고, kyobo.link 는 도메인이 없어졌다. 서점이 직접 운영하는 aladin.kr 은 바로 상품 페이지로 가므로 허용.
UNTRUSTED_SHORTLINK = re.compile(
    r'^https?://(www\.)?(bit\.ly|url\.kr|kyobo\.link|han\.gl|me2\.do|vo\.la|tinyurl\.com|goo\.gl)/', re.I)

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


def series_name(series) -> str:
    return SERIES_OFFICIAL_NAME.get(series.name, series.name)


def series_menu_name(series) -> str:
    return SERIES_MENU_NAME.get(series.name, series.name)


def series_number(series, index: Optional[str]) -> str:
    """시리즈 규칙대로 자리수를 맞춘 번호. 번호 없는 시리즈나 빈 값이면 ''. 숫자가 아니면 그대로."""
    digits = SERIES_NUMBER_DIGITS.get(series.name)
    raw = (index or '').strip()
    if not digits or not raw:
        return ''
    return str(int(raw)).zfill(digits) if raw.isdigit() else raw


def series_label(series, index: Optional[str]) -> str:
    return f'{series_name(series)} {series_number(series, index)}'.strip()


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
    if saved and not UNTRUSTED_SHORTLINK.match(saved):
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


def ebook_url(book, store: str) -> Optional[str]:
    saved = (getattr(book, EBOOK_FIELD[store], '') or '').strip()
    if saved and not UNTRUSTED_SHORTLINK.match(saved):
        return saved
    code = isbn13(book.ebook_isbn)
    return EBOOK_SEARCH_URL[store].format(isbn=code) if code and store in EBOOK_SEARCH_URL else None


def ebook_links(book) -> List[StoreLink]:
    links = []
    for store, label in EBOOK_STORES:
        url = ebook_url(book, store)
        if url:
            links.append(StoreLink(store, label, url))
    return links


def link_url(book, store: str) -> Optional[str]:
    """/go/ 가 보낼 주소. 종이책·전자책 서점 모두."""
    if store in dict(STORES):
        return store_url(book, store)
    if store in EBOOK_FIELD:
        return ebook_url(book, store)
    return None


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

# 소제목: 보도자료의 굵은 소제목이 옮겨지며 서식을 잃고 '짧은 한 줄 문단'으로 남은 것.
# 문장처럼 끝나지 않고, 따옴표·기호로 시작하지 않으며, 바로 뒤에 본문 문단이 이어질 때만 소제목으로 본다.
SUBHEAD_MAX = 45
BODY_MIN, BODY_SENTENCE_MIN = 80, 20
NOT_SUBHEAD_END = re.compile(r'([.。?!…,:;”’"\')」』\]]|다|요|추천사)$')
SENTENCE_END = re.compile(r'([.。?!…”’"\')」』]|다)$')
NOT_SUBHEAD_START = re.compile(r'^[“‘"\'「『(\[―\-–—*<《∵_+·•]')
# 옛 책 소개에 섞인 연락처(@)·글쓴이 표기(_, |)·쪽수가 붙은 차례 줄(005책머리에)
NOT_SUBHEAD_ANY = re.compile(r'[@_|]|^0\d\d')
EXCERPT = re.compile(r'본문|중에서')   # 시 구절처럼 짧은 줄이 많은 발췌 구획은 건드리지 않는다

Lines = List[str]


@dataclass
class Paragraph:
    html: SafeString
    subhead: bool = False


@dataclass
class Section:
    title: Optional[str]
    anchor: str = ''
    lead: Optional[SafeString] = None
    paragraphs: List[Paragraph] = field(default_factory=list)
    collapsible: bool = False


def render_lines(lines: Lines) -> SafeString:
    return mark_safe('<br>'.join(render_inline(l) for l in lines))


def plain(lines: Lines) -> str:
    return ''.join(strip_marks(l) for l in lines)


def subhead_shaped(lines: Lines) -> bool:
    text = plain(lines)
    return (len(lines) == 1 and 2 <= len(text) <= SUBHEAD_MAX
            and not NOT_SUBHEAD_END.search(text) and not NOT_SUBHEAD_START.match(text)
            and not NOT_SUBHEAD_ANY.search(text))


def body_like(lines: Lines) -> bool:
    text = plain(lines)
    return len(text) >= BODY_MIN or (len(text) >= BODY_SENTENCE_MIN and bool(SENTENCE_END.search(text)))


def with_subheads(paras: List[Lines]) -> List[Paragraph]:
    """본문 앞의 소제목 모양 줄을 소제목으로. 두 줄 연달아면 한 소제목으로 합치고, 셋 이상이면(시 구절·목록) 그대로 둔다."""
    out: List[Paragraph] = []
    run = 0   # 지금까지 이어진 소제목 모양 문단 수
    for i, lines in enumerate(paras):
        run = run + 1 if subhead_shaped(lines) else 0
        followed_by_body = i + 1 < len(paras) and body_like(paras[i + 1])
        if run in (1, 2) and followed_by_body:
            if run == 2:
                out.pop()
                lines = paras[i - 1] + lines
            out.append(Paragraph(render_lines(lines), subhead=True))
        else:
            out.append(Paragraph(render_lines(lines)))
    return out


def parse_description(text: str) -> List[Section]:
    """'■ 제목' 줄을 구획 제목으로, 빈 줄을 문단 경계로. 첫 구획의 짧은 첫 문단은 리드, 구획 안 소제목은 따로 표시."""
    sections = [Section(title=None)]
    raw: List[List[Lines]] = [[]]   # 구획별 문단(줄 목록)
    lines: Lines = []

    def flush():
        if lines:
            raw[-1].append(list(lines))
            lines.clear()

    for source in (text or '').splitlines():
        line = ZERO_WIDTH.sub('', source).strip()
        heading = HEADING.match(line)
        if heading:
            flush()
            title = heading.group(1).strip() or '소개'
            sections.append(Section(title=title, collapsible='차례' in title))
            raw.append([])
        elif line:
            lines.append(line)
        else:
            flush()
    flush()

    intro = raw[0]
    if intro and len(plain(intro[0])) <= LEAD_MAX:
        sections[0].lead = render_lines(intro.pop(0))
    for section, paras in zip(sections, raw):
        if section.collapsible or EXCERPT.search(section.title or ''):
            section.paragraphs = [Paragraph(render_lines(p)) for p in paras]
        else:
            section.paragraphs = with_subheads(paras)
    sections = [s for s in sections if s.lead or s.paragraphs]
    if len(sections) > 1 and sections[0].title is None:
        sections[0].title = '책 소개'
    for i, s in enumerate(sections, 1):
        s.anchor = f'section-{i}'
    return sections
