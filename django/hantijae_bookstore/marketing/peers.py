"""공개 참고 출판사 글: 계정 안의 반응 비교와 참여를 검토할 공개 자리. 원문은 호출 중에만 쓴다."""
import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from statistics import median
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

from django.db.models import Q

from intake.llm import complete_json
from intake.models import WorkerState
from marketing import meta
from marketing.candidates import Candidate
from marketing.models import Proposal, Signal
from marketing.moment_dates import date_supported
from marketing.prompts import PEER_SYSTEM
from marketing.text import similarity
from marketing.timeutil import KST
from web.blog import fetch_rss as read_rss

BASELINE_DAYS, FRESH_DAYS, FETCH_LIMIT, BATCH_LIMIT = 90, 14, 100, 5
KINDS = ('event', 'reprint', 'recruit', 'editorial', 'other')
_NUMBER = re.compile(r'(?<!\d)[+-]?\d+(?:,\d{3})*(?:\.\d+)?')


@dataclass(frozen=True)
class Source:
    channel: str
    account: str
    publisher: str

    @property
    def key(self):
        return f'{self.channel}:{self.account}'


PUBLISHERS = (
    ('마티', 'matibooks', 'matibook'), ('오월의봄', 'maybooks_05', ''), ('이음', 'eum_books', ''),
    ('글항아리', 'bookpot', ''), ('이김', 'leekim_publishing_house', ''),
    ('혜화1117', 'hyehwa1117', 'hyehwa11-17'), ('메멘토', 'memento_publishing_co', 'mementopub'),
    ('북스톤', 'bookstone.kr', 'book-stone'), ('마누스', 'manus_book', 'manus2020'),
)
SOURCES = tuple(Source(channel, account, publisher) for publisher, instagram, blog in PUBLISHERS
                for channel, account in (('ig', instagram), ('blog', blog)) if account)


@dataclass
class Report:
    new: list = field(default_factory=list)
    checked: int = 0
    failures: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Post:
    key: str
    url: str
    text: str
    posted_at: datetime
    likes: int = 0
    comments: int = 0


class SourceUnavailable(Exception):
    pass


def _plain(value, limit):
    if not isinstance(value, str):
        return ''
    value = re.sub(r'<(?:script|style)\b[^>]*>.*?</(?:script|style)>', '', value, flags=re.S | re.I)
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', value)).split())[:limit]


def _blog_url(value, account):
    """글 번호를 보존하고 추적 인자만 버린다. RSS의 외부·다른 계정 링크는 받지 않는다."""
    parts = urlsplit(value or '')
    if parts.scheme not in ('https', 'http') or parts.hostname not in ('blog.naver.com', 'm.blog.naver.com'):
        return ''
    path = parts.path.strip('/').split('/')
    query = parse_qs(parts.query)
    if len(path) == 2 and path[0] == account and path[1].isdigit():
        number = path[1]
    elif parts.path == '/PostView.naver' and query.get('blogId') == [account]:
        number = (query.get('logNo') or [''])[0]
    else:
        return ''
    return f'https://blog.naver.com/{account}/{number}' if number.isdigit() else ''


def _posts(source, business_media, fetch_rss):
    if source.channel == 'ig':
        rows = business_media(source.account, limit=FETCH_LIMIT)
        if rows is None:
            raise SourceUnavailable('instagram unavailable')
        return [Post(f'peer:ig:{m.id}', m.url, m.caption[:6000], m.posted_at, max(0, m.likes), max(0, m.comments))
                for m in rows if m.id and m.url and m.posted_at]
    root = ElementTree.fromstring(fetch_rss(f'https://rss.blog.naver.com/{source.account}.xml', timeout=10))
    if root.tag != 'rss' or root.find('channel') is None:
        raise SourceUnavailable('not RSS')
    out = []
    for item in list(root.iter('item'))[:FETCH_LIMIT]:
        url = _blog_url(item.findtext('link'), source.account)
        try:
            at = parsedate_to_datetime(item.findtext('pubDate') or '')
        except (ValueError, TypeError, IndexError):
            continue
        if not url or at.tzinfo is None:
            continue
        text = _plain((item.findtext('title') or '') + '\n' + (item.findtext('description') or ''), 6000)
        out.append(Post('peer:blog:' + hashlib.sha256(url.encode()).hexdigest()[:32], url, text, at))
    return out


def _unknown_numbers(text, source):
    """작은 인원·참가비도 사실이다. 자릿수와 무관하게 원문에 없는 숫자를 거른다."""
    def numbers(value):
        return {Decimal(value.replace(',', '')) for value in _NUMBER.findall(value)}
    return bool(numbers(text) - numbers(source))


def _event(raw, post, cancelled=False):
    if not isinstance(raw, dict):
        return None
    if not cancelled and (raw.get('public') is not True or raw.get('collaboration') is not True):
        return None
    try:
        day = date.fromisoformat(raw.get('date') or '')
    except (ValueError, TypeError):
        return None
    posted = post.posted_at.astimezone(KST).date()
    evidence = _plain(raw.get('evidence'), 180)
    # 날짜를 상상하거나, 다른 출판사의 참가 사실만으로 한티재도 참여할 수 있다고 넘겨짚지 않는다.
    invitation = re.search(r'(취소|중단|열리지)' if cancelled else
                           r'(모집|신청|접수|참여.{0,12}(가능|환영)|함께.{0,12}(해요|하세요|합시다|참여))', evidence)
    if (not evidence or evidence not in _plain(post.text, 6000) or not invitation
            or not date_supported(day, [(post.text, posted)])
            or not posted - timedelta(days=7) <= day <= posted + timedelta(days=120)):
        return None
    name, place = _plain(raw.get('name'), 80), _plain(raw.get('place'), 80)
    opportunity = '' if cancelled else _plain(raw.get('opportunity'), 120)
    # 장소·이름도 원문에 없는 고유 정보를 덧붙이지 못하게 한다.
    if not name or name not in post.text or (place and place not in post.text) or (not cancelled and not opportunity):
        return None
    if _unknown_numbers(opportunity, post.text):
        return None
    return {'date': day.isoformat(), 'name': name, 'place': place, 'opportunity': opportunity}


def _verdict(raw, post):
    if not isinstance(raw, dict):
        return None
    if any(not isinstance(raw.get(key), bool) for key in ('sensitive', 'cancelled')):
        return None
    summary = _plain(raw.get('summary'), 180)
    if not summary or _unknown_numbers(summary, post.text):
        return None
    return {'summary': summary, 'type': raw.get('type') if raw.get('type') in KINDS else 'other',
            'sensitive': raw.get('sensitive') is True, 'cancelled': raw.get('cancelled') is True,
            'event': _event(raw.get('event'), post, cancelled=raw['cancelled'])}


def _text_hash(post):
    return hashlib.sha256(post.text.encode()).hexdigest()


def _baseline(previous, posts, today):
    rows = {p['id']: p for p in previous if isinstance(p, dict) and p.get('id')
            and (today - timedelta(days=BASELINE_DAYS)).isoformat() <= p.get('posted_on', '') <= today.isoformat()}
    for post in posts:
        rows[post.key] = {'id': post.key, 'posted_on': post.posted_at.astimezone(KST).date().isoformat(),
                          'likes': post.likes, 'comments': post.comments}
    return sorted(rows.values(), key=lambda p: (p['posted_on'], p['id']), reverse=True)[:FETCH_LIMIT]


def run(llm, today, now, sources=None, business_media=None, fetch_rss=None):
    """출처별 한 번, 새 글 최대 다섯 개씩 판정한다. 한 출처 실패는 다른 출처의 완료를 막지 않는다."""
    report = Report()
    if WorkerState.get('peer_mode', 'off') != 'live':
        return report
    state = WorkerState.get('peer_scan_state', {}) or {}
    states = dict(state.get('sources') or {})
    for source in SOURCES if sources is None else sources:
        previous = states.get(source.key) or {}
        current = {**previous, 'attempted_at': now.isoformat(), 'checked': 0, 'new': 0}
        try:
            rows = _posts(source, business_media or meta.business_media, fetch_rss or read_rss)
            posts = sorted({p.key: p for p in rows
                            if now - timedelta(days=BASELINE_DAYS) <= p.posted_at <= now}.values(),
                           key=lambda p: (p.posted_at, p.key), reverse=True)
            report.checked += len(posts)
            current['checked'] = len(posts)
            if source.channel == 'ig':
                current['baseline'] = _baseline(previous.get('baseline') or [], posts, today)
            fresh = []
            for post in posts:
                existing = Signal.objects.filter(key=post.key).first()
                if existing:
                    existing.detail = {**existing.detail, 'likes': post.likes, 'comments': post.comments,
                                       'checked_at': now.isoformat()}
                    if existing.detail.get('text_hash') != _text_hash(post):
                        existing.relevant = False  # 바뀐 안내를 재확인하기 전에는 옛 참가 조건으로 제안하지 않는다
                        fresh.append(post)
                    existing.save(update_fields=['detail', 'relevant'])
                elif post.posted_at >= now - timedelta(days=FRESH_DAYS):
                    fresh.append(post)
            batch = fresh[:BATCH_LIMIT]
            current['backlog'] = len(fresh)
            if batch:
                user = json.dumps({'publisher': source.publisher, 'source': source.key,
                                   'posts': [{'id': i, 'posted_on': p.posted_at.astimezone(KST).date().isoformat(),
                                              'text': p.text} for i, p in enumerate(batch)]}, ensure_ascii=False)
                raw = complete_json(llm, PEER_SYSTEM, user)
                entries = raw.get('items') if isinstance(raw, dict) else None
                by_id = {r.get('id'): r for r in entries if isinstance(r, dict)
                         and type(r.get('id')) is int} if isinstance(entries, list) else {}
                invalid = False
                for i, post in enumerate(batch):
                    v = _verdict(by_id.get(i), post)
                    if not v:
                        invalid = True
                        continue
                    event = v.pop('event')
                    sensitive = v.pop('sensitive')
                    old = Signal.objects.filter(key=post.key).first()
                    if old and not event and (v['cancelled'] or sensitive):
                        event = old.detail.get('event')  # 취소 글이 날짜를 지워도 같은 모집을 닫을 수 있게
                    detail = {**v, 'source': source.key, 'channel': source.channel, 'publisher': source.publisher,
                              'account': source.account, 'posted_on': post.posted_at.astimezone(KST).date().isoformat(),
                              'likes': post.likes, 'comments': post.comments, 'checked_at': now.isoformat(),
                              'event': event, 'paid': 'unknown', 'text_hash': _text_hash(post)}
                    signal, created = Signal.objects.update_or_create(key=post.key, defaults={
                        'kind': 'peer', 'title': f'{source.publisher} ― {v["summary"]}', 'url': post.url[:1000],
                        'detail': detail, 'sensitive': sensitive, 'relevant': not v['cancelled'],
                        'happens_on': date.fromisoformat(event['date']) if event else None})
                    if created:
                        report.new.append(signal)
                        current['new'] += 1
                    current['backlog'] -= 1
                if invalid:
                    raise SourceUnavailable('incomplete judgement')
            current.update(success_at=now.isoformat(), failure_count=0, error='')
        except Exception as error:
            # HTTP 예외 본문에는 인증 정보가 들어갈 수 있다. 원문·주소·오류 내용은 상태에 남기지 않는다.
            name = type(error).__name__
            current.update(failure_count=int(previous.get('failure_count') or 0) + 1, error=name)
            report.failures[source.key] = name
        states[source.key] = current
        WorkerState.put('peer_scan_state', {'sources': states})
    return report


def _active():
    return Signal.objects.filter(kind='peer', relevant=True, sensitive=False).order_by('-found_at', '-id')


def _candidate_items(today, now, check_sent=True):
    if WorkerState.get('peer_mode', 'off') != 'live':
        return []
    out, blocked = [], set()
    signals = Signal.objects.filter(kind='peer', happens_on__gte=today,
                                    happens_on__lte=today + timedelta(days=21)).order_by('id')
    for signal in signals:
        d, event = signal.detail, signal.detail.get('event') or {}
        if not event:
            continue
        key = f'peer:{signal.id}'
        sent = check_sent and Proposal.objects.filter(candidate_key=key).filter(
            Q(briefing__sent_at__isnull=False) | Q(kind=Proposal.NOW, sent_at__isnull=False)).exists()
        # 같은 모집이 인스타·블로그에 실렸으면 가까운 후보 하나로 묶는다.
        same = next((c for c in out if c.facts['date'] == event['date']
                     and similarity(c.facts['name'], event['name']) >= 0.8), None)
        if same:
            same.more_signals.append(signal)
            if sent or d.get('cancelled') or signal.sensitive or not signal.relevant:
                blocked.add(same.id)
            continue
        out.append(Candidate(id=key, kind='peer_event', books=[], urgency=2, signal=signal,
                             summary=f'{d.get("publisher", "참고 출판사")} 소식: {event["name"]} ― 참여 검토',
                             facts={**event, 'source': d.get('publisher', ''), 'url': signal.url,
                                    'attendance': '한티재 참석 미정. 공개 참가 조건을 확인한 뒤 검토'}, link=signal.url))
        if sent or d.get('cancelled') or signal.sensitive or not signal.relevant:
            blocked.add(key)
    return sorted((c for c in out if c.id not in blocked), key=lambda c: (c.facts['date'], c.id))


def candidate_items(today, now):
    """가까운 공개 모집만 참여 검토 후보로. 공개 글 초안에서 한티재 참석을 단정하면 안 된다."""
    return _candidate_items(today, now)


def can_send(proposal, today, now):
    """발송 직전 현재 모집 가능 여부를 읽는다. 생성 뒤 들어온 다른 출처의 취소도 같은 묶음에 반영한다.
    미리보기의 sent_at이나 이 제안의 존재는 모집 가능 여부와 별개이므로 여기서는 확인하지 않는다."""
    if not proposal.signal_id or proposal.candidate_key != f'peer:{proposal.signal_id}':
        return False
    return any(proposal.signal_id in {c.signal.id, *(s.id for s in c.more_signals)}
               for c in _candidate_items(today, now, check_sent=False))


def briefing_lines(today, now):
    """최근 글에서 최대 두 출판사를 참고한다. 좋아요 절대 수로 서로 순위를 매기지 않는다."""
    if WorkerState.get('peer_mode', 'off') != 'live':
        return []
    state = WorkerState.get('peer_scan_state', {}) or {}
    sources = state.get('sources') or {}
    ranked = []
    for signal in _active():
        d = signal.detail
        if not (today - timedelta(days=7)).isoformat() <= d.get('posted_on', '') <= today.isoformat():
            continue
        if d.get('cancelled'):
            continue
        ratio = None
        if d.get('channel') == 'ig':
            baseline = [p['likes'] for p in sources.get(d.get('source'), {}).get('baseline', [])
                        if (today - timedelta(days=BASELINE_DAYS)).isoformat() <= p.get('posted_on', '')
                        < d.get('posted_on', '') and p.get('id') != signal.key and isinstance(p.get('likes'), int)]
            if len(baseline) >= 5 and median(baseline) > 0:
                ratio = d.get('likes', 0) / median(baseline)
        ranked.append((ratio, d.get('posted_on', ''), signal))
    ranked.sort(key=lambda row: (row[0] if row[0] is not None else -1, row[1], row[2].pk), reverse=True)
    lines, publishers = [], set()
    for ratio, _, signal in ranked:
        d = signal.detail
        publisher = d.get('publisher', '참고 출판사')
        if publisher in publishers:
            continue
        note = ''
        if d.get('channel') == 'ig':
            note = (f'좋아요가 관측한 이전 글 중앙값의 {ratio:.1f}배' if ratio is not None else '비교할 글이 아직 부족함')
            note = f' ({note} · 광고 여부 모름)'
        lines.append(f'{publisher}: {d.get("summary", signal.title)}{note}\n{signal.url}')
        publishers.add(publisher)
        if len(lines) == 2:
            break
    return lines
