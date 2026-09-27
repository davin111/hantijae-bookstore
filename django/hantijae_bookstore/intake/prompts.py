import json

EXTRACT_SYSTEM = """당신은 출판사 보도자료에서 도서 정보를 정확히 옮겨 적는 도우미입니다.
- 웹 검색·웹 페치 도구를 사용하지 마세요. 첨부된 자료에 있는 내용만 사용합니다.
- 자료에 없는 값은 null로 두고 추측하지 마세요.
- 소개글(short_description, description)은 원문 문장을 그대로 옮기고, PDF의 줄바꿈 때문에 끊긴 문장만 이어 붙이세요. 단어를 바꾸거나 요약하지 마세요. 문단 사이는 빈 줄(\\n\\n)로 구분합니다.
- JSON 객체 하나만 출력하세요."""

EXTRACT_SCHEMA = {
    "title": "제목", "subtitle": "부제 또는 null",
    "authors": [{"name": "이름", "role": "지은이|옮긴이|엮은이|기획"}],
    "series": "시리즈 이름(예: 한티재 팸플릿) 또는 null", "series_number": "시리즈 번호(예: 028) 또는 null",
    "category_hint": "보도자료의 '분야' 원문", "category": "아래 카테고리 목록 중 가장 알맞은 하나(정확히 같은 문자열) 또는 null",
    "size": "판형(예: 130×200)", "page_count": 0, "price": 0,
    "isbn": "ISBN-13 (하이픈 포함, 부가기호 제외)", "isbn_addon": "부가기호 5자리 또는 null",
    "published_date": "YYYY-MM-DD",
    "short_description": "'■ 책 소개' 첫 문단. 없으면 상단 홍보 문구",
    "description": "'■ 출판사 서평' 전체 원문. 없으면 '■ 책 소개' 전체",
    "images": [{"filename": "첨부 이미지 파일명", "kind": "front_flat|3d|other"}],
    "best_3d": "입체 이미지 중 흰 배경·그림자/띠지 없는 기본형 파일명 또는 null",
}


def build_extract_user(categories, series, image_names, local_text=''):
    parts = [
        '첨부한 보도자료에서 다음 JSON 형식으로 도서 정보를 추출하세요.',
        json.dumps(EXTRACT_SCHEMA, ensure_ascii=False, indent=1),
        f"카테고리 목록: {json.dumps(categories, ensure_ascii=False)}",
        f"사이트 시리즈 목록: {json.dumps(series, ensure_ascii=False)}",
        f"첨부 이미지: {json.dumps(image_names, ensure_ascii=False)}",
    ]
    if local_text:
        parts.append('보도자료 원문(PDF가 없어 텍스트로 전달):\n<document>\n' + local_text[:45000] + '\n</document>')
    return '\n\n'.join(parts)


PATCH_SYSTEM = """당신은 출판사 사이트의 도서 정보 수정 요청을 구조화된 변경 목록으로 바꾸는 도우미입니다.
- 웹 도구를 사용하지 마세요.
- 요청에 명시된 부분만 바꾸고, 언급되지 않은 필드는 절대 넣지 마세요.
- 소개글을 고칠 때는 요청된 부분 외의 문장을 그대로 유지하세요.
- '책 소개'·'소개글'은 description(상세 소개), '요약'·'짧은 소개'는 short_description 입니다.
- 요청에 인용된 문장이나 '첫 행' 같은 위치 표현이 있으면 현재 도서 정보에서 그 필드와 위치를 스스로 찾으세요. 찾을 수 있으면 필드를 되묻지 마세요.
- 사이트 표시 규칙: 소개글의 줄바꿈(\\n)은 그대로 줄바꿈으로, 빈 줄(\\n\\n)은 문단 간격으로 보입니다. `**문장**`으로 감싼 부분은 굵게 보입니다. 그 밖의 서식(기울임·밑줄·색·글자 크기·링크)은 지원하지 않으니, 요청되면 changes 없이 questions에 지원하지 않는다고 짧게 알리고 대안을 제안하세요.
- 구분선 모양을 따로 말하지 않으면 '* * *' 를 앞뒤로 빈 줄을 둔 별도 줄로 넣으세요.
- '이 초안의 지난 대화'가 주어지면 이번 메시지는 그 흐름의 연속입니다. 봇 질문에 대한 답이면 원래 요청과 합쳐서 처리하고, 앞선 요청을 없던 일로 하려는 뜻(예: '취소', '그건 됐어')이면 cancel_previous 를 true 로 하세요.
- 요청이 모호하거나 어떤 값으로 바꿔야 할지 확실하지 않으면 changes를 비우고 questions에 짧은 한국어 질문을 넣으세요.
- 허용 필드: title, subtitle, authors, series, series_number, category, size, page_count, full_price, isbn, published_date, short_description, description
- authors 값은 [{"name": "...", "role": "지은이|옮긴이|엮은이|기획"}] 전체 목록입니다.
- JSON 객체 하나만 출력: {"changes": [{"field": "...", "new_value": ...}], "questions": ["..."], "cancel_previous": false, "message": ""}
- message: 바꿀 것도 되물을 것도 없을 때(예: 취소 확인) 사용자에게 보낼 짧은 한국어 답. 그 밖에는 빈 문자열."""


MAX_USER_CHARS = 48000   # 사이드카 /complete userMessage 한도 50,000자에 여유를 둔다


def build_patch_user(current, source_text, request, history=()):
    head = '현재 도서 정보:\n' + json.dumps(current, ensure_ascii=False, indent=1)
    talk = ('이 초안의 지난 대화(오래된 순):\n' + '\n'.join(f'- {h}' for h in history)) if history else ''
    tail = '수정 요청:\n' + request
    # 대화 맥락과 현재 정보는 온전히 두고, 참고용 원문이 남는 분량만 쓴다
    budget = MAX_USER_CHARS - len(head) - len(talk) - len(tail) - 100
    source = (source_text or '')[:max(0, min(30000, budget))]
    parts = [head, '보도자료 원문(참고용):\n<document>\n' + source + '\n</document>'] + ([talk] if talk else []) + [tail]
    return '\n\n'.join(parts)
