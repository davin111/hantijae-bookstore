"""구글 알리미 RSS(Atom)와 유튜브 검색 결과를 서평 길의 Post로 바꾼다. 알리미 링크는 구글 리디렉트라 원래 주소를 꺼낸다.
유튜브 키는 주소 쿼리에 들어가므로 오류는 종류 이름만 담은 SourceError로 올린다(키·주소를 남기지 않게)."""
import html
import json
import urllib.parse
from datetime import date, timezone
from xml.etree import ElementTree

from marketing.review_search import Post, clean
from marketing.social_parse import parse_time
from marketing.timeutil import KST

ATOM = {'a': 'http://www.w3.org/2005/Atom'}
YOUTUBE_URL = 'https://www.googleapis.com/youtube/v3/search?'


class SourceError(Exception):
    """주소·키를 담지 않은 오류."""


def unwrap(url):
    parts = urllib.parse.urlsplit(url or '')
    if parts.netloc.endswith('google.com') and parts.path == '/url':
        target = urllib.parse.parse_qs(parts.query).get('url')
        if target:
            return target[0]
    return url


def feeds(cfg):
    try:
        value = json.loads(cfg.get('GOOGLE_ALERTS_FEEDS') or '[]')
    except ValueError:
        return []
    return [u for u in value if isinstance(u, str) and u] if isinstance(value, list) else []


def _day(value):
    at = parse_time(value)
    return at.astimezone(KST).date() if at else None


def parse_alerts(xml_bytes):
    out = []
    for e in ElementTree.fromstring(xml_bytes).findall('a:entry', ATOM):
        link = e.find('a:link', ATOM)
        url = unwrap(link.get('href') if link is not None else '')
        if not url:
            continue
        out.append(Post('web', url, clean(e.findtext('a:title', namespaces=ATOM)),
                        clean(e.findtext('a:content', namespaces=ATOM)), _day(e.findtext('a:published', namespaces=ATOM))))
    return out


def youtube_search(query, key, published_after, get_json):
    # KST 시간을 UTC로 변환
    utc_time = published_after.astimezone(timezone.utc)
    params = {'part': 'snippet', 'type': 'video', 'order': 'date', 'maxResults': 25, 'q': query, 'key': key,
              'publishedAfter': utc_time.strftime('%Y-%m-%dT%H:%M:%SZ')}
    try:
        data = get_json(YOUTUBE_URL + urllib.parse.urlencode(params))
    except Exception as e:
        raise SourceError(type(e).__name__) from None
    out = []
    for it in (data or {}).get('items') or []:
        vid = (it.get('id') or {}).get('videoId')
        sn = it.get('snippet') or {}
        if vid:
            out.append(Post('youtube', f'https://www.youtube.com/watch?v={vid}', html.unescape(sn.get('title') or ''),
                            html.unescape(sn.get('description') or '')[:200], _day(sn.get('publishedAt'))))
    return out
