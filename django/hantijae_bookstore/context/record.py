"""텔레그램 메시지(Bot API 형태)를 가린 기록으로 남긴다. 켜짐 여부와 검수 방인지는 부르는 쪽(intake 봇)이 판단한다."""
from collections import Counter
from datetime import datetime, timezone

from context.models import DEFAULT_ROLE, FORGET_FIELDS, ContextEntry
from context.redact import redact
from context.roles import resolve_role

# animation 메시지에는 document 도 같이 오고, venue 메시지에는 location 도 같이 온다 → 순서대로 먼저 맞는 것
MEDIA_ORDER = ('animation', 'photo', 'video', 'video_note', 'voice', 'audio', 'document', 'sticker', 'contact',
               'venue', 'location', 'poll')
FILE_KINDS = ('animation', 'video', 'video_note', 'voice', 'audio', 'document')
FORWARD_KEYS = ('forward_origin', 'forward_from', 'forward_from_chat', 'forward_sender_name')


def _key(chat_id, message_id):
    return f'tg:{chat_id}:{message_id}'


def _ts(seconds):
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _author(msg):
    user = msg.get('from')
    if user:
        name = ' '.join(p for p in (user.get('first_name', ''), user.get('last_name', '')) if p)
        return user.get('id'), name, '봇' if user.get('is_bot') else resolve_role(user.get('id'), name)
    return None, (msg.get('sender_chat') or {}).get('title', ''), DEFAULT_ROLE


def _content(msg):
    """본문·첨부 칸. 새로 기록할 때와 수정을 반영할 때 같이 쓴다. 연락처 번호는 어디에도 남기지 않는다."""
    kind = next((k for k in MEDIA_ORDER if k in msg), '')
    text = msg['poll'].get('question', '') if kind == 'poll' else (msg.get('text') or msg.get('caption') or '')
    text, counts = redact(text)
    name, file_id = '', ''
    if kind == 'photo':
        file_id = msg['photo'][-1].get('file_id', '')
    elif kind in FILE_KINDS:
        file_id = msg[kind].get('file_id', '')
        name, name_counts = redact(msg[kind].get('file_name', ''))
        counts = dict(Counter(counts) + Counter(name_counts))
    return {'text': text, 'redactions': counts, 'media': 'location' if kind == 'venue' else kind,
            'media_name': name[:200], 'file_id': file_id[:200]}


def record_telegram(msg):
    """새 메시지를 기록한다. 워커가 같은 업데이트를 다시 받아도 한 줄만 남는다."""
    chat_id, message_id = msg['chat']['id'], msg['message_id']
    author_id, name, role = _author(msg)
    reply = msg.get('reply_to_message') or {}
    entry, _ = ContextEntry.objects.get_or_create(key=_key(chat_id, message_id), defaults=dict(
        source=ContextEntry.TELEGRAM, origin=ContextEntry.LIVE, chat_id=chat_id, message_id=message_id,
        reply_to_id=reply.get('message_id'), reply_to_bot=bool((reply.get('from') or {}).get('is_bot')),
        at=_ts(msg['date']), author_id=author_id, author_name=name[:100], role=role,
        forwarded=any(k in msg for k in FORWARD_KEYS), **_content(msg)))
    return entry


def apply_edit(msg):
    """수정된 메시지를 반영한다. 기록에 없던 메시지(기록을 켜기 전 등)와 지운 기록은 건드리지 않는다."""
    entry = ContextEntry.objects.filter(key=_key(msg['chat']['id'], msg['message_id'])).first()
    if entry is None or entry.forgotten:
        return None
    old_file, old_text = entry.file_id, entry.text
    for field, value in _content(msg).items():
        setattr(entry, field, value)
    if entry.file_id != old_file:  # 사진 자체가 바뀌면 읽은 글을 버리고 다시 읽게 한다
        entry.media_text, entry.media_read_at = '', None
    if entry.text != old_text:  # 글이 바뀌면 링크도 바뀌었을 수 있다 → 다음 계기 잡기 때 다시 읽는다
        entry.link_text, entry.link_read_at = '', None
    entry.edited_at = _ts(msg.get('edit_date') or msg['date'])
    entry.save()
    return entry


def forget(chat_id, message_id, sent_at=None):
    """운영진이 /잊어 로 부탁한 메시지의 기록 내용을 지운다(키는 남김). 지운 기록 번호 목록을 돌려준다(없으면 빈 목록).

    실시간 기록이 없으면 내보내기로 가져온 기록을 보낸 시각으로 찾는다 — 번호 공간이 달라 번호로는 못 찾는다.
    같은 초에 온 가져온 메시지가 여럿이면 모두 지운다(덜 지우는 것보다 낫다).
    """
    rows = ContextEntry.objects.filter(key=_key(chat_id, message_id))
    if not rows.exists() and sent_at is not None:
        rows = ContextEntry.objects.filter(chat_id=chat_id, origin=ContextEntry.EXPORT, at=sent_at)
    ids = list(rows.values_list('id', flat=True))
    if ids:
        ContextEntry.objects.filter(id__in=ids).update(**FORGET_FIELDS)
    return ids
