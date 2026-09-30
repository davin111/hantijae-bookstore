"""글 속 유튜브 링크의 제목·채널·공개일·조회 수·설명을 읽어 기록(link_text)에 붙인다(2026-09-30).

왜: 운영진은 '박강수 방송. 이런 것도 홍보 소재가 될까?'처럼 링크만 올리고 내용을 쓰지 않는다. 계기 잡기 LLM은
링크를 열지 않으므로(웹 도구 금지) 무슨 방송인지 모른 채 흐릿한 계기를 만든다.
안전: 방에 올라온 주소를 그대로 열지 않는다. 영상 번호(11자)만 뽑아 youtube.com 주소를 코드가 만든다(내부망 요청 불가).
읽기(get)는 부르는 쪽이 넘긴다 — context 는 intake·marketing 을 import 하지 않는다.
"""
import json
import logging
import re
from zoneinfo import ZoneInfo

from context.models import ContextEntry
from context.redact import redact

log = logging.getLogger('intake')
KST = ZoneInfo('Asia/Seoul')
LIMIT, PER_ENTRY, DESC, KEEP = 20, 3, 400, 1500
WATCH_URL = 'https://www.youtube.com/watch?v={}'
OEMBED_URL = 'https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v={}'
_ID = re.compile(r'(?:youtu\.be/|youtube\.com/(?:watch\?(?:[^\s#]*?&)?v=|shorts/|live/|embed/))([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])')
_PLAYER = 'ytInitialPlayerResponse = '


def video_ids(text):
    out = []
    for vid in _ID.findall(text or ''):
        if vid not in out:
            out.append(vid)
    return out


def youtube_info(vid, get):
    """영상 페이지의 플레이어 정보(ytInitialPlayerResponse)를 읽는다. 없으면 oEmbed(제목·채널만)."""
    page = get(WATCH_URL.format(vid))
    i = page.find(_PLAYER)
    if i >= 0:
        try:
            data, _ = json.JSONDecoder().raw_decode(page, i + len(_PLAYER))
        except ValueError:
            data = {}
        d = data.get('videoDetails') or {}
        mf = (data.get('microformat') or {}).get('playerMicroformatRenderer') or {}
        if d.get('title'):
            views = str(d.get('viewCount') or '')
            return {'title': d['title'], 'channel': d.get('author', ''),
                    'published': (mf.get('publishDate') or mf.get('uploadDate') or '')[:10],
                    'views': int(views) if views.isdigit() else None, 'description': d.get('shortDescription', '')}
    o = json.loads(get(OEMBED_URL.format(vid)))
    return {'title': o['title'], 'channel': o.get('author_name', ''), 'published': '', 'views': None, 'description': ''}


def summary(info, now):
    """'[유튜브] 「제목」 · 채널 · 2026-09-29 공개 · 조회 수 658,084회(10/1 05:00 기준)' + 다음 줄 '설명: …'."""
    t = now.astimezone(KST)
    parts = [f"[유튜브] 「{info['title']}」", info['channel'],
             f"{info['published']} 공개" if info['published'] else '',
             f"조회 수 {info['views']:,}회({t.month}/{t.day} {t:%H:%M} 기준)" if info['views'] is not None else '']
    desc = ' '.join(info['description'].split())[:DESC]
    return ' · '.join(p for p in parts if p) + (f'\n설명: {desc}' if desc else '')


def read_links(entries, now, get, limit=LIMIT):
    """아직 읽지 않은 유튜브 링크가 있는 기록마다 한 번 읽어 저장한다. 못 읽어도 읽은 것으로 적고 넘어간다
    (계기 잡기를 막지 않는다). 글을 붙인 기록 수를 돌려준다."""
    todo = [e for e in entries if not e.forgotten and e.link_read_at is None and video_ids(e.text)][:limit]
    n = 0
    for e in todo:
        parts = []
        for vid in video_ids(e.text)[:PER_ENTRY]:
            try:
                parts.append(summary(youtube_info(vid, get), now))
            except Exception:
                log.warning('유튜브 링크를 읽지 못함(건너뜀): %s', vid, exc_info=True)
        text = redact('\n'.join(parts))[0][:KEEP] if parts else ''
        ContextEntry.objects.filter(pk=e.pk, forgotten=False).update(link_text=text, link_read_at=now)
        n += bool(text)
    return n
