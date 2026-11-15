"""검수 중 다시 받은 보도자료. 원자료 저장과 책 내용 반영을 분리한다."""
import hashlib
import os
import re
import unicodedata
import zipfile

from django.db import transaction
from django.utils import timezone

from intake import drafts
from intake.extract import EXTRACTORS, ExtractError, extract_text
from intake.prompts import build_patch_user

MAX_SOURCE_CHARS = 45000
DEFAULT_REQUEST = ('새 보도자료를 기준으로 도서 정보와 소개의 수정안을 준비해 주세요. '
                   '추천·인물 소개·차례를 포함한 원문 구획과 문장을 보존해 주세요.')


def _title_key(value):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFC', value)).casefold()


def _matches_book(text, book):
    isbn = re.sub(r'\D', '', book.isbn or '')
    found = {re.sub(r'\D', '', x) for x in re.findall(r'97[89](?:[ -]?\d){10}', text)}
    # 관련 도서에 대상 ISBN이 등장해도 이 책의 자료라는 뜻은 아니다.
    # 복수 ISBN이나 저장된 ISBN과의 충돌은 제목이 같아도 자동 교체하지 않는다.
    if len(found) > 1 or (isbn and found and found != {isbn}):
        return False
    title = _title_key(book.title)
    for line in text.splitlines()[:30]:
        line = re.sub(r'^\s*(?:책\s*제목|도서명|제목)\s*[:：|]?\s*', '', line)
        if title and _title_key(line) == title:
            return True
    return False


def replace_source(draft, path, actor, request=''):
    if os.path.splitext(path)[1].lower() not in EXTRACTORS:
        raise drafts.PatchError('보도자료는 DOCX·PDF·HWPX·HWP 파일로 보내 주세요')
    if os.path.getsize(path) > 20 * 1024 * 1024:
        raise drafts.PatchError('20MB가 넘는 자료예요. 파일을 나눠서 보내 주세요')
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            if sum(x.file_size for x in archive.infolist()) > 80 * 1024 * 1024:
                raise drafts.PatchError('압축을 풀면 너무 큰 자료예요. PDF로 내보내서 보내 주세요')
    try:
        text = extract_text(path)
    except ExtractError as e:
        raise drafts.PatchError('첨부 자료를 읽지 못했어요. 기존 자료는 그대로예요. 파일을 확인해 다시 보내 주세요.') from e
    if not text.strip():
        raise drafts.PatchError('첨부 자료에서 글을 읽지 못했어요. 글자가 선택되는 문서로 다시 보내 주세요')
    if len(text) > MAX_SOURCE_CHARS:
        raise drafts.PatchError('자료가 길어 전체를 읽을 수 없어요. 기존 자료는 보존했어요. 보도자료 부분만 따로 보내 주세요')
    if not _matches_book(text, draft.book):
        raise drafts.PatchError(f'이 자료가 『{draft.book.title}』의 보도자료인지 확인하지 못했어요. 제목이나 ISBN을 확인해 주세요. 기존 자료는 그대로예요.')
    # 새 원자료를 온전히 전달할 수 없으면 기존 원자료/대기안을 닫기 전에 멈춘다.
    try:
        build_patch_user(drafts.book_snapshot(draft.book), text, request or DEFAULT_REQUEST, require_full_source=True)
    except ValueError as e:
        raise drafts.PatchError('자료와 현재 본문을 함께 읽기에는 너무 길어요. 기존 자료와 대기 수정안은 보존했어요. 보도자료를 구획별로 나눠 주세요.') from e
    with open(path, 'rb') as source:
        digest = hashlib.sha256(source.read()).hexdigest()
    with transaction.atomic():
        current = drafts.lock_current(draft.pk, draft.version)
        if current.source_text != draft.source_text:
            raise drafts.StaleError('그사이 다른 자료가 등록됐어요. 최신 카드에서 다시 요청해 주세요')
        if (current.files.get('source_revision') or {}).get('sha256') == digest:
            return current, False
        files = dict(current.files)
        history = list(files.get('source_history', []))
        history.append({'text': current.source_text, 'revision': files.get('source_revision'),
                        'replaced_at': timezone.now().isoformat()})
        files['source_history'] = history
        files['source_revision'] = {'path': path, 'filename': os.path.basename(path), 'sha256': digest,
                                    'received_at': timezone.now().isoformat(), 'actor': actor}
        current.source_text, current.files = text, files
        current.save(update_fields=['source_text', 'files', 'updated_at'])
        drafts.cancel_open_patches(current)
    return current, True
