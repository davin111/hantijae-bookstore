"""Telegram Desktop HTML 내보내기(messages.html, messages2.html …)를 읽는다. 가림은 하지 않는다(가져오기 명령이 한다).

일반 그룹 내보내기의 메시지 번호는 내보낸 사람 계정의 번호라 봇이 받는 번호와 다르다 → 가져오기는 tgx: 키를 쓴다.
"""
import html
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
MONTHS = {m: i for i, m in enumerate(('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                                      'September', 'October', 'November', 'December'), 1)}
_DATE_EN = re.compile(r'(\d{1,2}) ([A-Za-z]+) (\d{4}), (\d{1,2}):(\d{2}):(\d{2})')
_DATE_NUM = re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{4}) (\d{1,2}):(\d{2}):(\d{2})')
_OFFSET = re.compile(r'UTC([+-])(\d{2}):(\d{2})')
_FILE = re.compile(r'messages(\d*)\.html')
_MEDIA = {'photo': 'photo', 'file': 'document', 'video': 'video', 'video_file': 'video', 'audio_file': 'audio',
          'voice_message': 'voice', 'contact': 'contact', 'location': 'location', 'live_location': 'location',
          'poll': 'poll', 'sticker': 'sticker', 'animation': 'animation'}
_NAMED_MEDIA = ('document', 'audio', 'video')


@dataclass
class ExportMessage:
    id: int
    at: datetime
    author: str
    text: str = ''
    reply_to: Optional[int] = None
    media: str = ''
    media_name: str = ''
    forwarded: bool = False


def parse_date(title):
    """'27 September 2026, 22:53:26' 또는 '27.09.2026 22:53:26', 뒤에 ' UTC+09:00' 이 붙을 수 있다. 없으면 한국 시간."""
    m = _DATE_EN.search(title)
    if m and m.group(2) in MONTHS:
        day, month, year = int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))
    else:
        m = _DATE_NUM.search(title)
        if not m:
            raise ValueError(f'시각을 읽지 못함: {title}')
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh, mm, ss = int(m.group(4)), int(m.group(5)), int(m.group(6))
    off = _OFFSET.search(title)
    tz = KST
    if off:
        sign = 1 if off.group(1) == '+' else -1
        tz = timezone(sign * timedelta(hours=int(off.group(2)), minutes=int(off.group(3))))
    return datetime(year, month, day, hh, mm, ss, tzinfo=tz)


def _clean(fragment):
    s = re.sub(r'<br\s*/?>', '\n', fragment)
    return html.unescape(re.sub(r'<[^>]+>', '', s)).strip()


def _field(block, cls):
    m = re.search(rf'<div class="{cls}">(.*?)</div>', block, re.S)
    return _clean(m.group(1)) if m else None


def _parse_block(block, last_author):
    ident = re.match(r'[^"]*" id="message(\d+)"', block)
    date = re.search(r'class="pull_right date details" title="([^"]+)"', block)
    if not ident or not date:
        raise ValueError('번호나 시각이 없음')
    reply = re.search(r'class="reply_to details">(?:(?!</div>).)*?GoToMessage\((\d+)\)', block, re.S)
    media = re.search(r'class="media clearfix pull_left media_(\w+)"', block)
    kind = _MEDIA.get(media.group(1), media.group(1)[:20]) if media else ('photo' if 'class="photo_wrap' in block else '')
    return ExportMessage(
        id=int(ident.group(1)), at=parse_date(date.group(1)), author=_field(block, 'from_name') or last_author,
        text=_field(block, 'text') or '', reply_to=int(reply.group(1)) if reply else None, media=kind,
        media_name=(_field(block, 'title bold') or '') if kind in _NAMED_MEDIA else '',
        forwarded='class="forwarded_from details"' in block or 'class="forwarded body"' in block)


def _files(folder):
    names = [n for n in os.listdir(folder) if _FILE.fullmatch(n)]
    if not names:
        raise FileNotFoundError(f'{folder} 에 messages*.html 이 없어요')
    names.sort(key=lambda n: int(_FILE.fullmatch(n).group(1) or 1))
    return [os.path.join(folder, n) for n in names]


def parse_export(folder):
    """(메시지 목록, 읽지 못한 메시지 수). 서비스 메시지는 뺀다. 이어 보낸 메시지는 파일이 바뀌어도 직전 발신자를 잇는다."""
    messages, errors, last_author = [], 0, ''
    for path in _files(folder):
        with open(path, encoding='utf-8') as fh:
            blocks = fh.read().split('<div class="message ')[1:]
        for block in blocks:
            if block.startswith('service'):
                continue
            try:
                msg = _parse_block(block, last_author)
            except ValueError:
                errors += 1
                continue
            last_author = msg.author
            messages.append(msg)
    return messages, errors
