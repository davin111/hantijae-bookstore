"""구글 뉴스 RSS 기사 주소를 언론사 원래 주소로 바꾼다(브리핑의 '기사 원문' 링크용).

구글 뉴스 RSS의 기사 주소(news.google.com/rss/articles/<id>)는 길고, HTTP로 넘겨주지 않고 브라우저 스크립트로
기사에 넘어간다. 원래 주소는 구글 뉴스 페이지가 쓰는 내부 호출(batchexecute 'Fbv4je')로만 얻는다:
① 기사 페이지에서 서명(data-n-a-sg)·시각(data-n-a-ts)을 읽고 ② 그 둘과 기사 id로 내부 호출을 보내면 원래 주소가 온다.
공식 API가 아니라 언제든 바뀔 수 있다 → 무엇이든 실패하면 받은 주소를 그대로 돌려준다(구글 뉴스 주소도 누르면 기사로 간다)."""
import json
import logging
import re
from urllib.parse import quote, urlparse

import requests

from marketing.http import UA, http_get

log = logging.getLogger('intake')
BATCH_URL = 'https://news.google.com/_/DotsSplashUi/data/batchexecute'
_SG = re.compile(r'data-n-a-sg="([^"]+)"')
_TS = re.compile(r'data-n-a-ts="(\d+)"')


def http_post_form(url, body, timeout=10):
    res = requests.post(url, data=body, timeout=timeout,
                        headers={'User-Agent': UA, 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'})
    res.raise_for_status()
    return res.text


def _article_id(url):
    p = urlparse(url)
    if p.netloc != 'news.google.com' or '/articles/' not in p.path:
        return None
    return p.path.rsplit('/', 1)[-1] or None


def original_url(url, get=http_get, post=http_post_form):
    gid = _article_id(url or '')
    if not gid:
        return url
    try:
        page = get(f'https://news.google.com/rss/articles/{gid}', timeout=10)
        sg, ts = _SG.search(page).group(1), _TS.search(page).group(1)
        req = (f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
               f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{gid}",{ts},"{sg}"]')
        text = post(BATCH_URL, 'f.req=' + quote(json.dumps([[['Fbv4je', req]]])))
        found = json.loads(json.loads(text.split('\n\n', 1)[1])[0][2])[1]
        if isinstance(found, str) and found.startswith(('https://', 'http://')):
            return found
        raise ValueError(f'원래 주소가 아님: {found!r}')
    except Exception:
        log.warning('구글 뉴스 주소를 원래 주소로 바꾸지 못함(그대로 씀): %s', url, exc_info=True)
    return url
