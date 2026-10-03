"""주간 브리핑 끝에 붙는 공식 채널 한 줄(스펙 §6 '어디에 힘을 쓸지'): 지난주 페북·인스타에 올린 글 수와 반응,
반응이 가장 큰 글. 코드가 만든다(LLM 아님). 올린 초안 하나의 2주 뒤 반응은 measure_line(placements)이 따로 적는다.
광고한 글은 '가장 큰 글'에서 빼고, 지난주 광고는 끝에 한 마디(marketing.ads)."""
from datetime import datetime, timedelta

from marketing import ads, meta
from marketing.timeutil import KST, week_start

HEAD = 24   # 가장 큰 글 앞부분 글자 수


def _total(p):
    return p.reactions + p.comments + p.shares


def _fb_part(fb):
    if fb is None:
        return '페북은 읽지 못했어요'
    if not fb:
        return '페북 글 없음'
    return (f'페북 {len(fb)}건 반응 {sum(p.reactions for p in fb)}·댓글 {sum(p.comments for p in fb)}·'
            f'공유 {sum(p.shares for p in fb)}')


def _ig_part(ig):
    if ig is None:
        return '인스타는 읽지 못했어요'
    if not ig:
        return '인스타 글 없음'
    return f'인스타 {len(ig)}건 좋아요 {sum(p.reactions for p in ig)}·댓글 {sum(p.comments for p in ig)}'


def week_line(today, fetch=meta.channel_posts):
    start = datetime.combine(week_start(today) - timedelta(days=7), datetime.min.time(), tzinfo=KST)
    paid_line = ads.week_text(start.date(), start.date() + timedelta(days=6))
    got = fetch(start, start + timedelta(days=7))
    fb, ig = got.get('facebook'), got.get('instagram')
    if fb is None and ig is None:
        return paid_line
    line = '지난주 공식 채널: ' + ', '.join([_fb_part(fb), _ig_part(ig)])
    posts = (fb or []) + (ig or [])
    paid = ads.post_ids()
    organic = [p for p in posts if p.id not in paid]
    if organic:
        top = max(organic, key=lambda p: (_total(p), p.posted_at))
        text = ' '.join(top.text.split())
        head = text if len(text) <= HEAD else text[:HEAD].rstrip() + '…'
        label = '광고하지 않은 글 중 반응이 가장 큰 글' if len(organic) < len(posts) else '반응이 가장 큰 글'
        line += (f'. {label}: {"페북" if top.channel == "facebook" else "인스타"} '
                 f'「{head}」(반응 합계 {_total(top)})')
    if paid_line:
        line += f'. {paid_line}'
    return line
