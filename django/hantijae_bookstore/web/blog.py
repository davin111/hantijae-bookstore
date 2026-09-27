"""네이버 블로그 최신 글. 운영진이 따로 손대지 않아도 첫 화면·소개 페이지가 새로워지게."""
import logging
import urllib.request
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from typing import List, Optional
from xml.etree import ElementTree

from django.core.cache import cache

log = logging.getLogger(__name__)
BLOG_URL = 'https://blog.naver.com/hantijae_publisher'
BLOG_RSS_URL = 'https://rss.blog.naver.com/hantijae_publisher.xml'
CACHE_KEY = 'web:blog_posts'
OK_TTL, FAIL_TTL = 3600, 600


@dataclass(frozen=True)
class BlogPost:
    title: str
    url: str
    date: Optional[date]
    category: str


def _date(text: str) -> Optional[date]:
    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError, IndexError):
        return None


def parse_rss(xml_bytes: bytes, limit: int = 3) -> List[BlogPost]:
    posts = []
    for item in ElementTree.fromstring(xml_bytes).iter('item'):
        title = (item.findtext('title') or '').strip()
        link = (item.findtext('link') or '').strip()
        if not title or not link.startswith('http'):
            continue
        posts.append(BlogPost(title, link.split('?')[0], _date(item.findtext('pubDate') or ''),
                              (item.findtext('category') or '').strip()))
        if len(posts) >= limit:
            break
    return posts


def fetch_rss(url: str = BLOG_RSS_URL, timeout: int = 3) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (hantijae-bookstore)'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(2_000_000)


def latest_posts(fetch=fetch_rss) -> List[BlogPost]:
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    try:
        posts = parse_rss(fetch())
        cache.set(CACHE_KEY, posts, OK_TTL)
    except Exception:  # 네트워크·XML 오류 — 페이지는 블로그 영역만 빼고 그린다
        log.warning('blog rss unavailable', exc_info=True)
        posts = []
        cache.set(CACHE_KEY, posts, FAIL_TTL)
    return posts
