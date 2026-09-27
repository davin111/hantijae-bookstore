"""사이트 곳곳에 쓰는 고정 정보. 채널 소개글은 블로그·인스타·X·페이스북 공통 문구(2026-09-27 확인)."""
from web.blog import BLOG_URL

SITE_NAME = '도서출판 한티재'
SITE_DESCRIPTION = ('도서출판 한티재는 권정생 선생님의 소설 『한티재 하늘』에서 이름을 따왔습니다. '
                    '작고 약한 것들을 사랑한 선생님의 정신을 따라, 작지만 다채롭고 소중한 가치를 담은 책, '
                    '모두의 다양성과 존엄을 지키는 책을 펴냅니다.')
TITLE_IMAGE_URL = 'https://hantijae-assets.s3.ap-northeast-2.amazonaws.com/misc/hantijae-bookstore-title.png'
MASCOT_IMAGE_URL = 'https://hantijae-assets.s3.ap-northeast-2.amazonaws.com/misc/kiki.jpeg'
FOUNDED_YEAR = 2010   # 2010-04-12 (블로그 2026-04-13 '16년 주년' 글)
ADDRESS = '42087 대구시 수성구 달구벌대로 492길 15 (2층)'
TEL, FAX, EMAIL = '053-743-8368', '053-743-8367', 'hantibooks@gmail.com'
CHANNELS = (
    ('블로그', BLOG_URL),
    ('인스타그램', 'https://www.instagram.com/hantijae'),
    ('X', 'https://x.com/hantijae_book'),
    ('페이스북', 'https://www.facebook.com/hantijae'),
    ('유튜브', 'https://www.youtube.com/channel/UCL_2QimPtgoDX3Y8e0qOBOA'),
)
# 헤더 오른쪽: 각 서점의 '한티재' 출판사 검색 결과 (옛 헤더 링크 그대로, 2026-09-27 동작 확인)
PUBLISHER_STORE_LINKS = (
    ('교보문고', 'https://search.kyobobook.co.kr/web/search?vPstrKeyWord=%ED%95%9C%ED%8B%B0%EC%9E%AC&orderClick=LAW&searchPubCd=26867&searchPcondition=1'),
    ('알라딘', 'https://www.aladin.co.kr/search/wsearchresult.aspx?PublisherSearch=%c7%d1%c6%bc%c0%e7@48149&BranchType=1'),
    ('YES24', 'https://www.yes24.com/Product/Search?&domain=ALL&company=%ED%95%9C%ED%8B%B0%EC%9E%AC&query=%25ED%2595%259C%25ED%258B%25B0%25EC%259E%25AC'),
)
# 책 상세의 저자 인터뷰 영상 (옛 React 화면의 id 109 하드코딩을 옮김)
AUTHOR_VIDEOS = {109: 'https://www.youtube-nocookie.com/embed/SGU5AzdzMNg'}
