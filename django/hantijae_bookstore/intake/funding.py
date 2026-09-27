"""알라딘 북펀드·텀블벅에서 한티재 명의 펀딩을 찾는다.
공식 API가 아니다(알라딘은 HTML, 텀블벅은 웹 화면용 내부 JSON) — 두 사이트 구조가 바뀌면 깨질 수 있다(2026-09-27 확인).
실패는 ScanResult.errors로 모아 호출하는 쪽(봇)이 관리자에게 알린다."""
import json
import logging
import re
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html import unescape
from typing import Callable, List, Optional, Tuple

from django.utils import timezone

from intake.models import FundingCampaign
from intake.notices import KST, kst_midnight

log = logging.getLogger('intake')
ALADIN_LIST_URL = 'https://www.aladin.co.kr/m/BookFund/Main.aspx'
ALADIN_VIEW_URL = 'https://www.aladin.co.kr/m/bookfund/view.aspx?pid={pid}'
TUMBLBUG_LIST_URL = 'https://tumblbug.com/api/v2/user/hantijae/project-list?page=1'
TUMBLBUG_PROJECT_URL = 'https://tumblbug.com/{permalink}'
PUBLISHER = '한티재'
MAX_ALADIN_FETCH = 30   # 한 번에 새로 열어 볼 알라딘 펀딩 수 (첫 가동 때 수십 건 — 나머지는 다음 확인 때)
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'


@dataclass
class Found:
    platform: str
    external_id: str
    url: str
    title: str
    publisher: str
    starts_at: Optional[datetime]
    ends_at: Optional[datetime]
    is_ours: bool


@dataclass
class ScanResult:
    new: List[FundingCampaign] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def http_get(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'ko-KR,ko;q=0.9'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(3_000_000).decode('utf-8', 'replace')


def aladin_pids(list_html: str) -> List[str]:
    return sorted(set(re.findall(r'bookfund/view\.aspx\?pid=(\d+)', list_html, re.I)), key=int, reverse=True)


def _text(html: str) -> str:
    return unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)))


def parse_aladin_view(pid: str, html: str) -> Found:
    text = _text(html)
    pub = re.search(r'펴낸곳\s*:\s*(.+?)\s+(?:판형|정가|출간일|※)', text)
    publisher = pub.group(1).strip() if pub else ''
    title_m = re.search(r'<meta property="og:title" content="([^"]*)"', html)
    title = unescape(title_m.group(1)).strip() if title_m else ''
    end_m = re.search(r'마감\s*(\d{4}-\d{2}-\d{2})', text)
    ends_at = kst_midnight(date.fromisoformat(end_m.group(1)) + timedelta(days=1)) if end_m else None
    return Found(FundingCampaign.ALADIN, pid, ALADIN_VIEW_URL.format(pid=pid), title, publisher, None, ends_at,
                 PUBLISHER in publisher)


def _kst(value) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value).replace(tzinfo=KST) if value else None
    except ValueError:
        return None


def parse_tumblbug(json_text: str) -> List[Found]:
    found = []
    for p in json.loads(json_text)['body']['result']['projects']:
        end = _kst(p.get('endDate'))
        found.append(Found(FundingCampaign.TUMBLBUG, p['permalink'],
                           TUMBLBUG_PROJECT_URL.format(permalink=p['permalink']), (p.get('title') or '').strip(),
                           '도서출판 한티재', _kst(p.get('fundingStartDate')),
                           end + timedelta(seconds=1) if end else None, True))
    return found


def is_live(found: Found, now) -> bool:
    return bool(found.ends_at and found.ends_at > now and (found.starts_at is None or found.starts_at <= now))


def _seen(platform: str, external_id: str) -> bool:
    return FundingCampaign.objects.filter(platform=platform, external_id=external_id).exists()


def _record(found: Found) -> FundingCampaign:
    return FundingCampaign.objects.create(platform=found.platform, external_id=found.external_id, url=found.url,
                                          title=found.title[:500], publisher=found.publisher[:200],
                                          starts_at=found.starts_at, ends_at=found.ends_at, is_ours=found.is_ours)


def _scan_aladin(get, now, sleep) -> Tuple[List[FundingCampaign], int]:
    pids = aladin_pids(get(ALADIN_LIST_URL))
    if not pids:
        raise ValueError('펀딩 목록이 비어 있음 (페이지 구조가 바뀌었을 수 있음)')
    new, fetched, unreadable = [], 0, 0
    for pid in pids:
        if fetched >= MAX_ALADIN_FETCH:
            break
        if _seen(FundingCampaign.ALADIN, pid):
            continue
        fetched += 1
        sleep(1)
        try:
            found = parse_aladin_view(pid, get(ALADIN_VIEW_URL.format(pid=pid)))
        except Exception:
            log.warning('aladin fund %s unreadable (page fetch/parse failed)', pid, exc_info=True)
            continue   # 기록하지 않아 다음 확인 때 다시 본다
        if not found.publisher:
            # 펴낸곳을 못 읽으면 우리 펀딩인지 알 수 없다 — '아님'으로 영구 기록하지 않고 다음 확인 때 다시 본다.
            # 마크업이 바뀌어 계속 못 읽으면 관리자에게 알려야 하므로 개수를 센다.
            log.warning('aladin fund %s unreadable (no 펴낸곳)', pid)
            unreadable += 1
            continue
        camp = _record(found)
        if found.is_ours and is_live(found, now):
            new.append(camp)
    return new, unreadable


def _scan_tumblbug(get, now) -> List[FundingCampaign]:
    new = []
    for found in parse_tumblbug(get(TUMBLBUG_LIST_URL)):
        if _seen(FundingCampaign.TUMBLBUG, found.external_id) or (found.starts_at and found.starts_at > now):
            continue   # 공개 예정 프로젝트는 시작한 뒤에 다시 본다
        camp = _record(found)
        if is_live(found, now):
            new.append(camp)
    return new


def scan(get: Callable[[str], str] = http_get, now=None, sleep=None) -> ScanResult:
    """처음 보는 '지금 진행 중인 한티재 펀딩'을 기록하고 돌려준다. 한 곳이 실패해도 다른 곳은 계속 본다."""
    now = now or timezone.now()
    sleep = sleep or time.sleep   # 호출 시점에 찾아야 테스트의 mock.patch('intake.funding.time.sleep')가 먹는다
    result = ScanResult()
    try:
        new, unreadable = _scan_aladin(get, now, sleep)
        result.new += new
        if unreadable:
            result.errors.append(f'알라딘 북펀드: 펴낸곳을 읽지 못한 펀딩 {unreadable}건')
    except Exception as e:
        log.warning('알라딘 북펀드 scan failed', exc_info=True)
        result.errors.append(f'알라딘 북펀드: {type(e).__name__}')
    try:
        result.new += _scan_tumblbug(get, now)
    except Exception as e:
        log.warning('텀블벅 scan failed', exc_info=True)
        result.errors.append(f'텀블벅: {type(e).__name__}')
    return result
