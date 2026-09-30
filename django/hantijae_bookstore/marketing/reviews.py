"""독자 서평 수집(스펙 §4, 결정 B): 책마다 네이버·카카오에서 찾고 → 코드로 1차 거르기 → 새 글만 LLM 1회 판별 → Signal(kind=review)."""
import logging

from intake.llm import complete_json
from marketing.prompts import REVIEW_JUDGE_SYSTEM, build_review_user
from marketing.review_search import SOURCE_LABEL

log = logging.getLogger('intake')
VERDICTS = ('review', 'promo', 'unrelated')
PER_LLM_CALL = 40


def _book_line(t):
    names = ', '.join(ba.author.name for ba in t.book.authors.all())
    sub = f' ― {t.book.subtitle}' if t.book.subtitle else ''
    return f'『{t.title}』{sub} (지은이: {names or "모름"})'


def judge(llm, rows):
    """rows: [(BookTerms, Post)] → {순번: (verdict, reason)}. 판정이 빠지거나 이상한 글은 넣지 않는다(다음에 다시 판별).
    한 묶음(40건) 호출이 실패하면 그 묶음만 빼고, 모든 묶음이 실패하면 예외."""
    out, failed, batches = {}, 0, 0
    for start in range(0, len(rows), PER_LLM_CALL):
        chunk = rows[start:start + PER_LLM_CALL]
        batches += 1
        user = build_review_user([(i, _book_line(t), SOURCE_LABEL[p.source], p.title, p.snippet, p.posted_on)
                                  for i, (t, p) in enumerate(chunk)])
        try:
            result = complete_json(llm, REVIEW_JUDGE_SYSTEM, user)
        except Exception:
            log.warning('review judge failed', exc_info=True)
            failed += 1
            continue
        for v in result.get('items') or []:
            if not isinstance(v, dict) or v.get('verdict') not in VERDICTS:
                continue
            try:
                i = int(v.get('id'))
            except (TypeError, ValueError):
                continue
            if 0 <= i < len(chunk):
                out[start + i] = (v['verdict'], str(v.get('reason') or '')[:200])
    if batches and failed == batches:
        raise RuntimeError(f'서평 판별 LLM 호출 {failed}번이 모두 실패했어요')
    return out
