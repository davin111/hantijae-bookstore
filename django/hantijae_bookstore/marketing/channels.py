"""주간 브리핑 끝에 붙는 공식 채널 한 줄(스펙 §6 '어디에 힘을 쓸지'): 지난주 페북·인스타에 올린 글 수와 반응,
반응이 가장 큰 글. 코드가 만든다(LLM 아님). 올린 초안 하나의 2주 뒤 반응은 measure_line(placements)이 따로 적는다."""
from datetime import datetime, timedelta

from marketing import meta
from marketing.timeutil import KST, week_start

HEAD = 24   # 가장 큰 글 앞부분 글자 수


def _total(p):
    return p.reactions + p.comments + p.shares


def week_line(today, fetch=meta.channel_posts):
    start = datetime.combine(week_start(today) - timedelta(days=7), datetime.min.time(), tzinfo=KST)
    got = fetch(start, start + timedelta(days=7))
    fb, ig = got.get('facebook'), got.get('instagram')
    if fb is None and ig is None:
        return ''
    parts = [('페북은 읽지 못했어요' if fb is None else
              f'페북 {len(fb)}건 반응 {sum(p.reactions for p in fb)}·댓글 {sum(p.comments for p in fb)}·'
              f'공유 {sum(p.shares for p in fb)}'),
             ('인스타는 읽지 못했어요' if ig is None else
              f'인스타 {len(ig)}건 좋아요 {sum(p.reactions for p in ig)}·댓글 {sum(p.comments for p in ig)}')]
    line = '지난주 공식 채널: ' + ', '.join(parts)
    posts = (fb or []) + (ig or [])
    if posts:
        top = max(posts, key=lambda p: (_total(p), p.posted_at))
        text = ' '.join(top.text.split())
        head = text if len(text) <= HEAD else text[:HEAD].rstrip() + '…'
        line += f'. 반응이 가장 큰 글: {"페북" if top.channel == "facebook" else "인스타"} 「{head}」 {_total(top)}'
    return line
