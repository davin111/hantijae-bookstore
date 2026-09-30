from datetime import date
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase

from marketing.review_search import (SOURCE_LABEL, Post, kakao_search, naver_search, normalize_url, parse_kakao,
                                     parse_naver, sources)

# 2026-09-30 실제 응답에서 옮겨 줄인 것
NAVER_BLOG = {'items': [{'title': '<b>커밍아웃 스토리</b> 독후감', 'link': 'https://blog.naver.com/ezihyuni/224310717154',
                         'description': '<b>커밍아웃 스토리</b> 성소수자부모모임2018한티재 &quot;어쩌다&quot;  읽게...',
                         'bloggername': 'Me', 'bloggerlink': 'https://blog.naver.com/ezihyuni', 'postdate': '20260609'},
                        {'title': '주소 없는 글', 'link': '', 'description': '', 'postdate': '20260609'}]}
NAVER_CAFE = {'items': [{'title': '2023년 10월 모임 후기', 'link': 'https://cafe.naver.com/rainbow/123?art=abc',
                         'description': '부모모임 &lt;커밍아웃 스토리&gt; 읽기', 'cafename': '무지개 <b>독서</b>모임',
                         'cafeurl': 'https://cafe.naver.com/rainbow'}]}
DAUM_BLOG = {'documents': [{'blogname': '인생봄심리상담센터', 'contents': '<b>커밍아웃</b> <b>스토리</b> 성소수자부모모임 2018 한티재',
                            'datetime': '2026-03-13T15:31:00.000+09:00', 'thumbnail': '', 'title': '<b>커밍아웃</b> <b>스토리</b>(5)',
                            'url': 'https://blog.naver.com/lifespring10042/224215219796'}], 'meta': {'total_count': 1}}
DAUM_CAFE = {'documents': [{'cafename': '퀴어 책 읽기', 'contents': '모임에서 읽었다', 'datetime': '', 'thumbnail': '',
                            'title': '[커밍아웃 스토리] 1장', 'url': 'https://cafe.daum.net/qaf/NFBh/2158'}], 'meta': {}}
CREDS_N, CREDS_K = {'id': 'nid', 'secret': 'nsec'}, {'key': 'kk'}


class Recorder:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        return self.reply


class ParseTest(SimpleTestCase):
    def test_parse_naver_blog(self):
        [p] = parse_naver('naver_blog', NAVER_BLOG)   # 주소 없는 글은 버린다
        self.assertEqual(p, Post('naver_blog', 'https://blog.naver.com/ezihyuni/224310717154', '커밍아웃 스토리 독후감',
                                 '커밍아웃 스토리 성소수자부모모임2018한티재 "어쩌다" 읽게...', date(2026, 6, 9), ''))

    def test_parse_naver_cafe_has_no_date_and_keeps_cafe_name(self):
        [p] = parse_naver('naver_cafe', NAVER_CAFE)
        self.assertEqual((p.posted_on, p.where, p.snippet), (None, '무지개 독서모임', '부모모임 <커밍아웃 스토리> 읽기'))

    def test_parse_kakao_blog_and_cafe(self):
        [b] = parse_kakao('daum_blog', DAUM_BLOG)
        self.assertEqual((b.title, b.posted_on, b.where), ('커밍아웃 스토리(5)', date(2026, 3, 13), ''))  # 블로그 이름은 적지 않는다
        [c] = parse_kakao('daum_cafe', DAUM_CAFE)
        self.assertEqual((c.posted_on, c.where), (None, '퀴어 책 읽기'))

    def test_normalize_url_merges_forms_of_one_post(self):
        same = ['https://blog.naver.com/lifespring10042/224215219796',
                'https://m.blog.naver.com/lifespring10042/224215219796',
                'http://blog.naver.com/PostView.naver?blogId=lifespring10042&logNo=224215219796',
                'https://blog.naver.com/lifespring10042/224215219796/']
        self.assertEqual({normalize_url(u) for u in same}, {'blog.naver.com/lifespring10042/224215219796'})
        self.assertEqual(normalize_url('https://cafe.naver.com/rainbow/123?art=abc'), 'cafe.naver.com/rainbow/123')
        self.assertEqual(normalize_url('https://www.Example.com/a/'), 'example.com/a')

    def test_normalize_url_keeps_legacy_naver_cafe_articles_distinct(self):
        a = normalize_url('https://cafe.naver.com/ArticleRead.nhn?clubid=1&articleid=2')
        b = normalize_url('https://cafe.naver.com/ArticleRead.nhn?clubid=1&articleid=3')
        self.assertNotEqual(a, b)


class SearchTest(SimpleTestCase):
    def test_naver_search_builds_request(self):
        get = Recorder(NAVER_BLOG)
        posts = naver_search('naver_blog', '"커밍아웃 스토리" 성소수자부모모임', CREDS_N, get)
        url, headers = get.calls[0]
        parts = urlsplit(url)
        self.assertEqual(parts.netloc + parts.path, 'naverapihub.apigw.ntruss.com/search/v1/blog')
        self.assertEqual(parse_qs(parts.query), {'query': ['"커밍아웃 스토리" 성소수자부모모임'], 'display': ['50'],
                                                 'sort': ['date']})
        self.assertEqual(headers, {'X-NCP-APIGW-API-KEY-ID': 'nid', 'X-NCP-APIGW-API-KEY': 'nsec'})
        self.assertEqual(len(posts), 1)
        naver_search('naver_cafe', '"x"', CREDS_N, get)
        self.assertIn('/search/v1/cafearticle?', get.calls[1][0])

    def test_kakao_search_builds_request(self):
        get = Recorder(DAUM_CAFE)
        kakao_search('daum_cafe', '"커밍아웃 스토리"', CREDS_K, get)
        url, headers = get.calls[0]
        parts = urlsplit(url)
        self.assertEqual(parts.netloc + parts.path, 'dapi.kakao.com/v2/search/cafe')
        self.assertEqual(parse_qs(parts.query), {'query': ['"커밍아웃 스토리"'], 'sort': ['accuracy'], 'size': ['50']})
        self.assertEqual(headers, {'Authorization': 'KakaoAK kk'})

    def test_sources_skip_missing_keys(self):
        self.assertEqual(sources({}), [])
        self.assertEqual(sources({'NAVER_HUB_CLIENT_ID': 'x'}), [])   # 비밀값이 없으면 네이버를 쓰지 않는다
        self.assertEqual([s for s, _, _ in sources({'KAKAO_REST_API_KEY': 'k'})], ['daum_blog', 'daum_cafe'])
        full = {'NAVER_HUB_CLIENT_ID': 'i', 'NAVER_HUB_CLIENT_SECRET': 's', 'KAKAO_REST_API_KEY': 'k'}
        self.assertEqual([s for s, _, _ in sources(full)], ['naver_blog', 'naver_cafe', 'daum_blog', 'daum_cafe'])
        self.assertEqual((SOURCE_LABEL['ig_tag'], SOURCE_LABEL['ig_partner']), ('인스타 태그', '인스타 협력 계정'))
