"""공공 선정 발표 출처(스펙 §5, 조사 .claude/docs/signals/2026-09-29/selection-sources.md).
스캐너마다 처음 보는 발표(seen에 없는 key)만 Announcement로 돌려준다. 대조는 selections.py가 한다."""
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

from marketing.doctext import document_text
from marketing.text import title_key

FRESH_DAYS = 60   # 이보다 오래된 발표는 기록만 한다(첫 실행 때 옛 공고로 알림이 쏟아지지 않게)
SPACING = 1.5


@dataclass
class Announcement:
    source: str
    key: str
    label: str
    url: str
    posted_on: Optional[date]
    fresh: bool
    texts: List[str] = field(default_factory=list)
    withdrawal: bool = False


def clean(html_fragment):
    """태그·'새글' 아이콘을 지우고 공백을 하나로."""
    s = re.sub(r"<span class='icon-pack-wrap'>.*?</span>\s*</span>", '', html_fragment or '', flags=re.S)
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', s)).strip()


def _download_texts(files, get_bytes, sleep):
    texts = []
    for url, name in files:
        sleep(SPACING)
        texts.append(document_text(name, get_bytes(url)))
    return texts


# ---- 한국출판문화산업진흥원 사업공고 [결과공고] — 세종도서 교양·학술, 문학나눔(2024~) ----
KPIPA_LIST = 'https://www.kpipa.or.kr/p/g1_2?sca=%EA%B2%B0%EA%B3%BC%EA%B3%B5%EA%B3%A0'
KPIPA_VIEW = 'https://www.kpipa.or.kr/p/g1_2/{no}'
KPIPA_PROGRAMS = ('세종도서', '문학나눔')
_KPIPA_ROW = re.compile(r"href='https://www\.kpipa\.or\.kr/p/g1_2/(\d+)[^']*' class='list-subject'>(.*?)</a>"
                        r".*?<div class=\"fz-date\">(\d{2})\.(\d{2})\.(\d{2})\.</div>", re.S)
_KPIPA_FILE = re.compile(r'<a href="(https://www\.kpipa\.or\.kr/p/download/g1_2/\d+/\d+/)" class="view_file_download">'
                         r'\s*<strong>(.*?)</strong>', re.S)


def kpipa_posts(html):
    return [(no, clean(raw).replace('[결과공고]', '').strip(), date(2000 + int(yy), int(mm), int(dd)))
            for no, raw, yy, mm, dd in _KPIPA_ROW.findall(html)]


def kpipa_files(html):
    return [(url, clean(name)) for url, name in _KPIPA_FILE.findall(html)]


def is_withdrawal(title):
    return bool(re.search(r'철회|취소', title))


def is_selection_title(title):
    return any(p in title for p in KPIPA_PROGRAMS) and ('결과' in title or is_withdrawal(title))


def kpipa_label(title):
    label = re.sub(r'\s*(도서\s*)?선정\s*(결과|철회|취소).*$', '', title)
    return label.replace(' 도서 보급 사업', '').replace(' 지원 사업', '').strip()


def scan_kpipa(today, seen, get_text, get_bytes, sleep):
    out = []
    for no, title, posted in kpipa_posts(get_text(KPIPA_LIST)):
        key = f'kpipa:{no}'
        if key in seen or not is_selection_title(title):
            continue
        view = KPIPA_VIEW.format(no=no)
        sleep(SPACING)
        files = [f for f in kpipa_files(get_text(view)) if f[1].lower().endswith(('.pdf', '.xlsx'))]
        lists = [f for f in files if '목록' in f[1]] or files   # 공고문·총평은 한글 글꼴이 깨져 대조에 쓸모없다
        out.append(Announcement('kpipa', key, kpipa_label(title), view, posted,
                                posted >= today - timedelta(days=FRESH_DAYS),
                                _download_texts(lists, get_bytes, sleep), is_withdrawal(title)))
    return out


# ---- 한국출판문화진흥재단 '올해의 청소년 교양도서' (반기, 엑셀에 출판사·ISBN) ----
TKPF_BASE = 'http://www.tkpf.or.kr'   # https는 열리지 않는다(조사 2026-09-29)
TKPF_LIST = TKPF_BASE + '/contents/community_notice.php'
TKPF_VIEW = TKPF_BASE + '/contents/community_notice_view.php?no={no}'
_TKPF_ROW = re.compile(r'href="/contents/readCountN\.php\?no=(\d+)[^"]*"[^>]*>(.*?)</a>', re.S)
_TKPF_FILE = re.compile(r'href="/contents/download\.php\?filename=([^"]+)"')
_DOT_DATE = re.compile(r'(20\d{2})\.(\d{2})\.(\d{2})')


def tkpf_posts(html):
    out = []
    for no, raw in _TKPF_ROW.findall(html):
        title = clean(raw)
        if '청소년 교양도서' in title and '결과' in title:
            out.append((no, title))
    return out


def tkpf_files(html):
    return [(TKPF_BASE + '/contents/download.php?filename=' + urllib.parse.quote(name), name.rsplit('/', 1)[-1])
            for name in _TKPF_FILE.findall(html)]


def tkpf_posted(html):
    m = _DOT_DATE.search(html)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def tkpf_label(title):
    m = re.search(r'(20\d{2})년\s*(상반기|하반기)', title)
    return f'{m.group(1)}년 {m.group(2)} 청소년 교양도서' if m else '올해의 청소년 교양도서'


def scan_tkpf(today, seen, get_text, get_bytes, sleep):
    out = []
    for no, title in tkpf_posts(get_text(TKPF_LIST)):
        key = f'tkpf:{no}'
        if key in seen:
            continue
        view = TKPF_VIEW.format(no=no)
        sleep(SPACING)
        html = get_text(view)
        posted = tkpf_posted(html)
        files = [f for f in tkpf_files(html) if f[1].lower().endswith('.xlsx')]
        fresh = bool(posted and posted >= today - timedelta(days=FRESH_DAYS))
        out.append(Announcement('tkpf', key, tkpf_label(title), view, posted, fresh,
                                _download_texts(files, get_bytes, sleep)))
    return out
