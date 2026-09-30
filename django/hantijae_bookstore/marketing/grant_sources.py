"""진흥원 사업공고(지원사업 공고) 목록·본문 읽기. 판단은 grants.py가 한다.
스펙 .claude/docs/specs/2026-09-30-grant-calls-design.md (로컬)."""
import html
import re
import urllib.parse
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

from marketing.selection_sources import KPIPA_VIEW, clean

GRANT_LIST = 'https://www.kpipa.or.kr/p/g1_2?sca=' + urllib.parse.quote('사업공고')
CATEGORY = '[사업공고]'
# 한티재(출판사)가 신청하는 사업이 아닌 것. 최근 60건에 적용하면 27건이 남는다(test_grant_sources에 고정)
EXCLUDE = ('보급 신청', '웹소설', '웹툰', '서점', '지자체', '교육생', '수강생', '교육 참가자', '인력', '코디네이터',
           '실태조사', '간담회', '선정위원', '심사위원', '독서경영', '그림책', '아동', '기술개발', '취업', 'Call for')
MAX_TEXT = 12000   # LLM에 보낼 본문 + 공고문 글자 수
_ROW = re.compile(r"href='https://www\.kpipa\.or\.kr/p/g1_2/(\d+)[^']*' class='list-subject'>(.*?)</a>"
                  r".*?<div class=\"fz-date\">(\d{2})\.(\d{2})\.(\d{2})\.</div>", re.S)
_TITLE = re.compile(r'<title>(.*?)</title>', re.S)
_BODY = re.compile(r'<div id="bo_v_con">(.*?)<!-- } 본문 내용 끝 -->', re.S)


@dataclass
class Post:
    no: str
    title: str
    posted_on: date

    @property
    def key(self):
        return f'kpipa:{self.no}'

    @property
    def url(self):
        return KPIPA_VIEW.format(no=self.no)


def grant_posts(page) -> List[Post]:
    out = []
    for no, raw, yy, mm, dd in _ROW.findall(page or ''):
        title = html.unescape(clean(raw)).replace(CATEGORY, '', 1).strip()
        out.append(Post(no, title, date(2000 + int(yy), int(mm), int(dd))))
    return out


def is_excluded(title):
    return any(w in title for w in EXCLUDE)


def view_title(page):
    """공고 페이지 제목(목록 제목은 길면 '…'로 잘린다)."""
    m = _TITLE.search(page or '')
    return html.unescape(m.group(1)).split(' > ')[0].strip() if m else ''


def view_text(page):
    """공고 본문 글자. 문단·줄바꿈은 살리고 태그·폭 없는 공백은 지운다."""
    m = _BODY.search(page or '')
    if not m:
        return ''
    text = re.sub(r'<br\s*/?>|</p>', '\n', m.group(1))
    text = html.unescape(re.sub(r'<[^>]+>', ' ', text)).replace('​', '')
    lines = (' '.join(line.split()) for line in text.split('\n'))
    return '\n'.join(line for line in lines if line)


def notice_file(files) -> Optional[Tuple[str, str]]:
    """첨부 가운데 공고문 PDF(이름에 '공고'), 없으면 첫 PDF."""
    pdfs = [f for f in files if f[1].lower().endswith('.pdf')]
    return next((f for f in pdfs if '공고' in f[1]), pdfs[0] if pdfs else None)
