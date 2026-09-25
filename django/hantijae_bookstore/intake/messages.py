"""텔레그램 문구·버튼 (순수 함수). callback_data는 64바이트 제한이라 ID와 버전만 싣는다."""
from intake.mapping import FIELD_LABELS
from intake.telegram_api import keyboard

CAPTION_LIMIT = 1024


def tg_len(s):
    """텔레그램은 길이를 UTF-16 코드 유닛으로 센다(이모지 = 2)."""
    return len(s.encode('utf-16-le')) // 2
ROLE_VERB = {'지은이': '지음', '옮긴이': '옮김', '엮은이': '엮음', '기획': '기획'}


def _authors(snap):
    return ' · '.join(f"{a['name']} {ROLE_VERB.get(a['role'], '지음')}" for a in snap.get('authors') or [])


def _meta(snap):
    parts = []
    if snap.get('series') and snap['series'] != '단행본':
        parts.append(f"{snap['series']} {snap.get('series_number') or ''}".strip())
    if snap.get('full_price'):
        parts.append(f"{snap['full_price']:,}원")
    if snap.get('page_count'):
        parts.append(f"{snap['page_count']}쪽")
    parts += [p for p in (snap.get('size'), snap.get('published_date')) if p]
    return ' · '.join(parts)


def _short(v, n=60):
    s = '' if v is None else (', '.join(f"{a['name']}({a['role']})" for a in v) if isinstance(v, list) else str(v))
    s = s.replace('\n', ' ')
    return s if len(s) <= n else s[:n - 1] + '…'


def draft_caption(snap, warnings, preview, published=False):
    head = ['✅ 공개됨' if published else '🔎 검수 대기', f"📕 {snap['title']}"]
    if snap.get('subtitle'):
        head.append(_short(snap['subtitle'], 120))
    head += [_authors(snap), _meta(snap), f"ISBN {snap.get('isbn') or '-'}"]
    tail = '\n'.join(['', f'미리보기 → {preview}', '고칠 내용은 이 메시지에 답장으로 적어 주세요.'])
    family = sorted((w for w in warnings if w['audience'] == 'family'), key=lambda w: not w['blocking'])
    lines = [f"{'🚫' if w['blocking'] else '⚠️'} {w['message']}" for w in family]
    # 경고를 뒤에서부터 줄여 1024자에 맞춘다. 미리보기 링크(tail)는 절대 자르지 않는다.
    for keep in range(len(lines), -1, -1):
        shown = lines[:keep] + ([f'… 외 {len(lines) - keep}건'] if keep < len(lines) else [])
        body = '\n'.join(head + ([''] + shown if shown else []))
        if tg_len(body) + tg_len(tail) <= CAPTION_LIMIT:
            return body + tail
    while body and tg_len(body) + tg_len(tail) > CAPTION_LIMIT:
        body = body[:-1]
    return body + tail


def draft_buttons(draft_id, version, published=False):
    rows = [[('🖼 입체 이미지 바꾸기', f'img:{draft_id}:{version}')]]
    if not published:
        rows = [[('✅ 이대로 공개', f'pub:{draft_id}:{version}')],
                [('🖼 입체 이미지 바꾸기', f'img:{draft_id}:{version}'), ('🗑 폐기', f'del:{draft_id}:{version}')]]
    return keyboard(rows)


def confirm_buttons(action, draft_id, version):
    return keyboard([[('예', f'{action}ok:{draft_id}:{version}'), ('아니요', 'noop')]])


def patch_text(snap, changes, questions):
    if questions and not changes:
        return '\n'.join(f'❓ {q}' for q in questions)
    lines = ['이렇게 바꿀게요'] + [
        f"• {FIELD_LABELS.get(c['field'], c['field'])}: {_short(snap.get(c['field']))} → {_short(c.get('new_value'))}"
        for c in changes]
    lines += [f'❓ {q}' for q in questions]
    return '\n'.join(lines)


def patch_buttons(patch_id):
    return keyboard([[('반영', f'apply:{patch_id}'), ('취소', f'cancel:{patch_id}')]])


def undo_buttons(revision_id):
    return keyboard([[('↩️ 되돌리기', f'undo:{revision_id}')]])


def parse_callback(data):
    action, *rest = (data or '').split(':')
    return action, [int(x) for x in rest if x.isdigit()]
