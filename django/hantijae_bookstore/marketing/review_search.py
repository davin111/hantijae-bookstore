"""독자 서평 검색: 네이버 API HUB(블로그·카페)와 카카오 다음 검색(블로그·카페). 결과를 한 모양(Post)으로 맞춘다.
네이버는 따옴표 구절 검색이 되지만 카페 글에 날짜가 없고, 카카오는 따옴표를 무시하지만 날짜가 있다(2026-09-30 실측)."""
import html
import re
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

NAVER_URL = 'https://naverapihub.apigw.ntruss.com/search/v1/{kind}?'
KAKAO_URL = 'https://dapi.kakao.com/v2/search/{kind}?'
PER_CALL = 50
SOURCE_LABEL = {'naver_blog': '네이버 블로그', 'naver_cafe': '네이버 카페', 'daum_blog': '다음 블로그', 'daum_cafe': '다음 카페'}


@dataclass
class Post:
    source: str
    url: str
    title: str
    snippet: str
    posted_on: Optional[date]
    where: str = ''   # 카페 이름. 블로그 이름·별명은 개인 표시라 적지 않는다


def clean(text):
    """검색 결과의 <b> 강조·HTML 엔티티를 벗기고 공백을 하나로."""
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', text or ''))).strip()


def normalize_url(url):
    """같은 글의 여러 주소(m.·www.·http/https·PostView.naver?blogId=&logNo=·끝의 /·쿼리)를 하나로."""
    parts = urllib.parse.urlsplit((url or '').strip())
    host = parts.netloc.lower()
    for prefix in ('m.', 'www.'):
        if host.startswith(prefix):
            host = host[len(prefix):]
    path = parts.path.rstrip('/')
    query = urllib.parse.parse_qs(parts.query)
    if host == 'blog.naver.com' and query.get('blogId') and query.get('logNo'):
        path = f"/{query['blogId'][0]}/{query['logNo'][0]}"
    if host == 'cafe.naver.com' and query.get('articleid'):   # 옛 ArticleRead.nhn?clubid=&articleid= 주소
        path = f"/{query.get('clubid', [''])[0]}/{query['articleid'][0]}"
    return host + path


def parse_naver(source, data):
    out = []
    for it in data.get('items') or []:
        if not it.get('link'):
            continue
        try:
            day = datetime.strptime(it.get('postdate') or '', '%Y%m%d').date()
        except ValueError:
            day = None   # 카페 글에는 날짜가 없다
        out.append(Post(source, it['link'], clean(it.get('title')), clean(it.get('description')), day,
                        clean(it.get('cafename')) if source == 'naver_cafe' else ''))
    return out


def parse_kakao(source, data):
    out = []
    for it in data.get('documents') or []:
        if not it.get('url'):
            continue
        try:
            day = date.fromisoformat((it.get('datetime') or '')[:10])   # '2026-03-13T15:31:00.000+09:00' → KST 날짜
        except ValueError:
            day = None
        out.append(Post(source, it['url'], clean(it.get('title')), clean(it.get('contents')), day,
                        clean(it.get('cafename')) if source == 'daum_cafe' else ''))
    return out


def naver_search(source, query, creds, get_json):
    kind = {'naver_blog': 'blog', 'naver_cafe': 'cafearticle'}[source]
    url = NAVER_URL.format(kind=kind) + urllib.parse.urlencode({'query': query, 'display': PER_CALL, 'sort': 'date'})
    return parse_naver(source, get_json(url, {'X-NCP-APIGW-API-KEY-ID': creds['id'], 'X-NCP-APIGW-API-KEY': creds['secret']}))


def kakao_search(source, query, creds, get_json):
    kind = {'daum_blog': 'blog', 'daum_cafe': 'cafe'}[source]
    url = KAKAO_URL.format(kind=kind) + urllib.parse.urlencode({'query': query, 'sort': 'accuracy', 'size': PER_CALL})
    return parse_kakao(source, get_json(url, {'Authorization': 'KakaoAK ' + creds['key']}))


def sources(cfg):
    """(출처, 검색 함수, 자격 증명). 키가 없는 출처는 뺀다(그 출처만 건너뛴다)."""
    out = []
    if cfg.get('NAVER_HUB_CLIENT_ID') and cfg.get('NAVER_HUB_CLIENT_SECRET'):
        creds = {'id': cfg['NAVER_HUB_CLIENT_ID'], 'secret': cfg['NAVER_HUB_CLIENT_SECRET']}
        out += [('naver_blog', naver_search, creds), ('naver_cafe', naver_search, creds)]
    if cfg.get('KAKAO_REST_API_KEY'):
        creds = {'key': cfg['KAKAO_REST_API_KEY']}
        out += [('daum_blog', kakao_search, creds), ('daum_cafe', kakao_search, creds)]
    return out
