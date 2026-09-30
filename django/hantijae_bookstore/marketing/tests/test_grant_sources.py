from datetime import date

from django.test import SimpleTestCase

from marketing.grant_sources import GRANT_LIST, grant_posts, is_excluded, notice_file, view_text, view_title
from marketing.selection_sources import kpipa_files


def row(no, title, yymmdd, cate='사업공고'):
    """진흥원 목록 한 줄(2026-09-30 실제 모양)."""
    return (f"<li class=\"\"><div class=\"fz-subject\"><a href='https://www.kpipa.or.kr/p/g1_2/{no}"
            f"?sca=%EC%82%AC%EC%97%85%EA%B3%B5%EA%B3%A0' class='list-subject'><span class=\"bo-cate-link\">[{cate}]</span>"
            f"{title}<span class='icon-pack-wrap'><span class='jyk_b_new'>새글</span></span></a></div>"
            f"<div class=\"fz-writer sv-empty-writer\"><span class=\"sv_member\">디지털콘텐츠팀</span></div>"
            f"<div class=\"fz-date\">{yymmdd}</div></li>")


def view(title, body, files=()):
    """공고 한 건 페이지(본문 영역·첨부 링크만)."""
    links = ''.join(f'<a href="https://www.kpipa.or.kr/p/download/g1_2/2167/{i}/" class="view_file_download">\n'
                    f'<strong>{name}</strong></a>' for i, name in enumerate(files))
    return (f'<html><head><title>{title} &gt; 사업공고 | 한국출판문화산업진흥원 대표 누리집</title></head><body>'
            f'<div id="bo_v_con"><p>{body}</p></div>\n                <!-- }} 본문 내용 끝 -->\n'
            f'<h2>첨부파일</h2>{links}</body></html>')


# 2026-03-19 ~ 2026-09-29 진흥원 사업공고 60건(목록에 보이는 그대로)
RECENT_TITLES = [
    '2026년 세종도서 지원 사업 선정도서 보급 신청 공고',
    '2026년 제3차 전자책 제작 지원 사업 공고',
    '2026년 웹소설 IP 2차 저작화 지원 사업 추가 모집 공고',
    '2026년 문학나눔 도서 보급 사업 선정도서 보급 신청 공고',
    '2026년 웹소설 일러스트 제작 지원 사업 추가 모집 공고',
    '2026년 웹소설 번역비 지원 사업 추가 모집 공고',
    '2026년 권역별 선도서점 육성 사업 컨설팅(경영·마케팅·디지털) 참여서점 추가 모집 공고',
    '2026년 글로벌 출판전문인력 양성 교육 참가자 모집 공고',
    '2026년 권역별 선도서점 육성 사업 컨설팅(경영·마케팅·디지털) 참여서점 모집 공고',
    '[한국서점연합회] 2026년 지역서점 스마트 기기 지원 참여 서점 모집(변경)',
    '2026년 하반기 수출아카데미 수강생 모집 공고',
    '2026년 하반기 KPIPA 디지털북센터 교육생 모집 공고(8.12.~마감 시) * 최종 …',
    '[한국서점연합회] 2026년 지역서점 공동수배송 운영 사업 추가 모집 공고',
    '2027 독서 기반 지역 활성화 참여 지자체 모집 공고',
    '2026년 제6차 수출용 홍보자료(샘플) 지원 사업 공고',
    '「2026 지역서점 실태조사」 실시 안내 및 참여 협조 요청',
    '2026년 수출아카데미 AI 활용 특강 수강생 모집 공고',
    '<지역서점 및 지역서점협동조합 확인 절차> 안내(2026년 1차)',
    '2026 대한민국 그림책상 공모',
    '2026년 한-불 출판 펠로우십 국내 참가사 모집 공고',
    '2027년 대한민국 독서대전 개최 지자체 모집 공고',
    '2026년 제5차 수출용 홍보자료(샘플) 지원 사업 공고',
    '2026년 출판콘텐츠 기술개발 지원 사업(후속과제) 공고',
    '2026년 출판콘텐츠 기술개발 지원 사업(신규과제) 공고',
    '2026년 독서경영 우수직장 인증 신청 공고',
    '2026 지역서점·협동조합 확인 제도 의견 수렴 간담회 개최(6.25.)',
    '2026년 한국출판문화산업진흥원 수출 코디네이터 2차 모집 공고',
    '2026년 상하이국제아동도서전 참가사 및 위탁도서 모집 공고',
    '2026년 데이터 마케팅 컨설팅 지원 사업 참여 출판사 추가 모집 공고',
    '2026년 찾아가는 밀라노(이탈리아) 도서전 참가사 및 위탁도서 모집 공고',
    '2026년 제4차 수출용 홍보자료(샘플) 지원 사업 공고',
    '2026년 제2차 전자책 제작 지원 사업 공고',
    '2026년 제2차 오디오북 제작 지원 사업 신청 공고',
    '2026년 제13회 대한민국 전자출판 대상 공모',
    '2026년 프랑크푸르트도서전 참가사 및 위탁도서 모집 공고',
    '2026년 웹소설 일러스트 제작 지원 사업 모집 공고',
    '2026년 서울국제도서전 참가 지원사업 지원사 모집 재공고(3차)',
    '2026년 제3차 수출용 홍보자료(샘플) 지원 사업 공고',
    '2026년 데이터 마케팅 컨설팅 지원 사업 참여 출판사 모집 연장 공고',
    'Call for Overseas Participants for 2026 K-Boo…',
    '2026년 확장형 전자출판물 제작 지원 사업 신청 공고',
    '2026년 찾아가는 뉴욕(미국) 도서전 참가사 및 위탁도서 모집 공고',
    '2026년 웹소설 번역비 지원 사업 추가 모집 공고',
    '2026년 상반기 KPIPA 디지털북센터 교육생 모집 공고(4.15.~마감 시) * 최종 …',
    '2026년 출판콘텐츠 해외 발간 지원 사업 모집 공고(2026 Overseas Public…',
    '2026년 서울국제도서전 참가 지원사업 지원사 모집 재공고',
    '2026년 상반기 수출아카데미 수강생 모집 공고',
    '2026년 웹소설 IP 2차 저작화 지원 사업 모집 공고',
    '2026년 도서 보급 나눔사업(문학나눔, 세종도서) 선정위원 후보자 공개 모집 공고',
    '2026년 수출전문인력 취업지원 사업 공고',
    '2026년 제2차 수출용 출판 홍보자료(샘플) 지원 사업 공고',
    '2026년 데이터 마케팅 컨설팅 지원 사업 참여 출판사 모집 공고',
    '2026년 출판사 마케팅 자율 지원 사업 참여 출판사 모집 공고',
    '2026년 서울국제도서전 참가 지원사업 지원사 모집 공고',
    '2026년 중소출판사 성장도약 제작지원 사업 공고',
    '2026년 웹소설 번역비 지원 사업 신청 공고',
    '2026년 세종도서 지원 학술부문 도서 신청 공고',
    '2026년 세종도서 지원 교양부문 도서 신청 공고',
    '2026년 문학나눔 도서 보급 사업 도서 신청 공고',
    '2026년 제1차 오디오북 제작 지원 사업 신청 공고',
]
# 제외 규칙 뒤에 남아 LLM이 판단할 27건
KEPT = [
    '2026년 제3차 전자책 제작 지원 사업 공고',
    '2026년 제6차 수출용 홍보자료(샘플) 지원 사업 공고',
    '2026년 한-불 출판 펠로우십 국내 참가사 모집 공고',
    '2026년 제5차 수출용 홍보자료(샘플) 지원 사업 공고',
    '2026년 데이터 마케팅 컨설팅 지원 사업 참여 출판사 추가 모집 공고',
    '2026년 찾아가는 밀라노(이탈리아) 도서전 참가사 및 위탁도서 모집 공고',
    '2026년 제4차 수출용 홍보자료(샘플) 지원 사업 공고',
    '2026년 제2차 전자책 제작 지원 사업 공고',
    '2026년 제2차 오디오북 제작 지원 사업 신청 공고',
    '2026년 제13회 대한민국 전자출판 대상 공모',
    '2026년 프랑크푸르트도서전 참가사 및 위탁도서 모집 공고',
    '2026년 서울국제도서전 참가 지원사업 지원사 모집 재공고(3차)',
    '2026년 제3차 수출용 홍보자료(샘플) 지원 사업 공고',
    '2026년 데이터 마케팅 컨설팅 지원 사업 참여 출판사 모집 연장 공고',
    '2026년 확장형 전자출판물 제작 지원 사업 신청 공고',
    '2026년 찾아가는 뉴욕(미국) 도서전 참가사 및 위탁도서 모집 공고',
    '2026년 출판콘텐츠 해외 발간 지원 사업 모집 공고(2026 Overseas Public…',
    '2026년 서울국제도서전 참가 지원사업 지원사 모집 재공고',
    '2026년 제2차 수출용 출판 홍보자료(샘플) 지원 사업 공고',
    '2026년 데이터 마케팅 컨설팅 지원 사업 참여 출판사 모집 공고',
    '2026년 출판사 마케팅 자율 지원 사업 참여 출판사 모집 공고',
    '2026년 서울국제도서전 참가 지원사업 지원사 모집 공고',
    '2026년 중소출판사 성장도약 제작지원 사업 공고',
    '2026년 세종도서 지원 학술부문 도서 신청 공고',
    '2026년 세종도서 지원 교양부문 도서 신청 공고',
    '2026년 문학나눔 도서 보급 사업 도서 신청 공고',
    '2026년 제1차 오디오북 제작 지원 사업 신청 공고',
]


class ListTest(SimpleTestCase):
    def test_list_url_filters_business_notices(self):
        self.assertEqual(GRANT_LIST, 'https://www.kpipa.or.kr/p/g1_2?sca=%EC%82%AC%EC%97%85%EA%B3%B5%EA%B3%A0')

    def test_posts_have_number_title_date_without_category_or_new_icon(self):
        page = ('<ul class="fz-list">' + row('2167', '2026년 제3차 전자책 제작 지원 사업 공고', '26.09.29.')
                + row('2119', '&lt;지역서점 확인 절차&gt; 안내', '26.07.13.') + '</ul>')
        posts = grant_posts(page)
        self.assertEqual([(p.no, p.title, p.posted_on) for p in posts],
                         [('2167', '2026년 제3차 전자책 제작 지원 사업 공고', date(2026, 9, 29)),
                          ('2119', '<지역서점 확인 절차> 안내', date(2026, 7, 13))])
        self.assertEqual((posts[0].key, posts[0].url), ('kpipa:2167', 'https://www.kpipa.or.kr/p/g1_2/2167'))

    def test_exclusion_rules_keep_publisher_programs(self):
        self.assertEqual([t for t in RECENT_TITLES if not is_excluded(t)], KEPT)


class ViewTest(SimpleTestCase):
    def test_title_body_and_notice_pdf(self):
        page = view('2026년 제3차 전자책 제작 지원 사업 공고',
                    '​2026년 제3차 전자책 제작 지원 사업 공고 안내드립니다.<br />신청 기간 10. 2.(금) ~ 10. 12.(월)',
                    files=('붙임1. 공고문2026년 제3차 전자책 제작 지원.pdf', '붙임2. 사업 관련 기준 및 제출 서식.zip',
                           '붙임3. 신청 안내 매뉴얼.pdf'))
        self.assertEqual(view_title(page), '2026년 제3차 전자책 제작 지원 사업 공고')
        self.assertEqual(view_text(page), '2026년 제3차 전자책 제작 지원 사업 공고 안내드립니다.\n'
                                          '신청 기간 10. 2.(금) ~ 10. 12.(월)')
        self.assertEqual(notice_file(kpipa_files(page)),
                         ('https://www.kpipa.or.kr/p/download/g1_2/2167/0/', '붙임1. 공고문2026년 제3차 전자책 제작 지원.pdf'))

    def test_notice_file_falls_back_to_first_pdf_or_none(self):
        self.assertEqual(notice_file([('u1', 'a.hwp'), ('u2', '매뉴얼.pdf')]), ('u2', '매뉴얼.pdf'))
        self.assertIsNone(notice_file([('u1', 'a.hwp')]))

    def test_missing_body_and_title_are_empty(self):
        self.assertEqual((view_text('<html></html>'), view_title('')), ('', ''))
