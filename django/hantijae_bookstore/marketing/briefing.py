"""주간 브리핑: 후보를 LLM에 한 번 보내 최대 4개를 고르게 하고, 코드로 다시 검증한다."""
import re
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from intake.llm import complete_json
from marketing import bnk_sales, candidates, channels, gnews, meta
from marketing.models import Briefing, Draft, Proposal, SalesSnapshot, Signal
from marketing.prompts import BRIEFING_SYSTEM, build_briefing_user
from marketing.sales import latest
from marketing.text import fix_title_marks, foreign_numbers
from marketing.timeutil import KST, week_start
from web.models import StoreClick

MAX_ITEMS = 4  # 3개면 저자 소식이 계기·기념일·펀딩에 밀려 빠졌다(2026-09-30). 주중 제안은 midweek.MAX_ITEMS(3)로 먼저 자른다
SALES_WORDS = ('구매', '주문', '할인', '서점에서', '링크', 'http', '가격')
MEMORIAL_REASON = '추모의 날이라 알리기만 하는 글이에요.'
_SENTENCE_END = re.compile(r'(?<=[.!?])\s+')
CHANNELS = (Draft.INSTAGRAM, Draft.BLOG, Draft.LETTER)


def _places(draft):
    """편지의 보낼 곳(draft.to). 빈 값은 빼고 5곳까지."""
    to = draft.get('to')
    return [p for p in (str(x).strip() for x in to) if p][:5] if isinstance(to, list) else []


def _without_sales_sentences(text):
    return ' '.join(x for x in _SENTENCE_END.split(text) if x and not any(w in x for w in SALES_WORDS))


def compose(llm, cands, today, context=(), midweek=False):
    if not cands:
        return [], []
    by_id = {c.id: c for c in cands}
    result = complete_json(llm, BRIEFING_SYSTEM, build_briefing_user(cands, today, context, midweek=midweek))
    items, dropped, used_books = [], [], set()
    for raw in result.get('items') or []:
        if not isinstance(raw, dict):
            continue
        cand = by_id.get(raw.get('candidate_id'))
        if cand is None:
            dropped.append(f'없는 후보: {raw.get("candidate_id")}')
            continue
        d = raw.get('draft') if isinstance(raw.get('draft'), dict) else {}
        headline = fix_title_marks(str(raw.get('headline', '')).strip())
        reason = str(raw.get('reason', '')).strip()
        body = fix_title_marks(str(d.get('body', '')).strip())
        if not headline or not body:
            dropped.append(f'{cand.id}: 빈 항목')
            continue
        places = _places(d) if d.get('channel') == Draft.LETTER else []
        bad = foreign_numbers(' '.join([headline, reason, body, *places]), cand.allowed_texts() + [today.isoformat()])
        if bad:
            dropped.append(f'{cand.id}: 자료에 없는 숫자 {", ".join(bad)}')
            continue
        if cand.memorial:
            # 게시되는 글(제목·본문)과 방에 그대로 보이는 headline은 엄격히 본다
            if any(w in ' '.join([headline, str(d.get('title', '')), body]) for w in SALES_WORDS):
                dropped.append(f'{cand.id}: 추모 성격의 날에 판매 권유')
                continue
            # reason은 운영진에게 하는 말이다. "구매 링크는 붙이지 않았어요" 같은 설명 때문에 항목을 버리지 않고 그 문장만 뺀다
            reason = _without_sales_sentences(reason) or MEMORIAL_REASON
        ids = {b.id for b in cand.books}
        if ids & used_books:
            dropped.append(f'{cand.id}: 같은 책이 이미 있음')
            continue
        used_books |= ids
        channel = d.get('channel') if d.get('channel') in CHANNELS else Draft.INSTAGRAM
        if places:  # 신간 묶음 편지와 같은 모양: 보낼 곳을 먼저, 그 아래 글
            body = '알리면 좋을 곳\n' + '\n'.join(f'· {p}' for p in places) + '\n\n보낼 글\n' + body
        items.append((cand, headline, reason,
                      {'channel': channel, 'title': fix_title_marks(str(d.get('title', '')).strip()), 'body': body}))
        if len(items) == MAX_ITEMS:
            break
    return items, dropped


def save_briefing(items, today):
    with transaction.atomic():  # 도중에 실패하면 옛 항목이 그대로 남는다(반쯤 만든 브리핑이 나가지 않게)
        briefing, _ = Briefing.objects.get_or_create(week_start=week_start(today))
        # 관리자가 /brief 로 다시 만들면 새 항목으로 바꾼다. 옛 항목이 쓴 저자 소식은 다시 후보가 되게 풀어 준다
        # 묶음 후보(서평·기사 모음)의 나머지 신호는 Proposal.extra['signals']에 적어 두었다
        more = [i for extra in briefing.items.values_list('extra', flat=True) for i in (extra or {}).get('signals', [])]
        Signal.objects.filter(Q(proposal__briefing=briefing) | Q(pk__in=more)).update(used_at=None)
        briefing.items.all().delete()
        for rank, (cand, headline, reason, d) in enumerate(items, 1):
            more_ids = [s.pk for s in cand.more_signals]
            extra = {'signals': more_ids} if more_ids else {}
            if cand.link:  # 브리핑 메시지에 '기사 원문: 주소'처럼 붙인다
                extra.update(link=cand.link, link_label=candidates.LINK_LABEL.get(cand.kind, '링크'))
            p = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=cand.books[0] if cand.books else None,
                                        signal=cand.signal, briefing=briefing, candidate_key=cand.id,
                                        headline=headline[:300], reason=reason, rank=rank, extra=extra)
            Draft.objects.create(proposal=p, channel=d['channel'], title=d['title'][:300], body=d['body'])
            used = ([cand.signal.pk] if cand.signal else []) + more_ids
            if used:
                Signal.objects.filter(pk__in=used).update(used_at=timezone.now())
    return briefing


def _store_click_count(book, day):
    start = datetime.combine(day, datetime.min.time(), tzinfo=KST)
    end = start + timedelta(days=14)
    return StoreClick.objects.filter(book=book, created_at__gte=start, created_at__lt=end).count()


def _where(draft):
    """봇이 찾은 게시 위치(placements.py). 못 찾았으면 빈 문자열 — 초안 종류(인스타 글)로 짐작하지 않는다."""
    labels = list(dict.fromkeys(p['label'] for p in draft.placements or [] if p.get('label')))
    return f'({"·".join(labels)})' if labels else ''


def _reactions(draft, counts):
    """공식 페북·인스타 글의 지금 반응 수. 못 읽은 채널은 뺀다."""
    out = []
    for p in draft.placements or []:
        if p.get('kind') not in ('facebook', 'instagram') or not p.get('id'):
            continue
        c = counts(p['kind'], p['id'])
        if not c:
            continue
        if p['kind'] == 'facebook':
            out.append(f"페북 페이지 반응 {c['reactions']}·댓글 {c['comments']}·공유 {c['shares']}")
        else:
            out.append(f"인스타 좋아요 {c['likes']}·댓글 {c['comments']}")
    return out


MEASURE_MAX = 300   # Briefing.measure 칸 길이


def _fit_measure(first, line):
    """성과 줄과 공식 채널 줄을 measure 칸에 넣는다. 넘치면 채널 줄의 '반응이 가장 큰 글' 부분을 빼고, 그래도 넘치면
    채널 줄을 뺀다 — 반쯤 잘린 줄을 운영진에게 보이지 않게. 성과 줄만으로 넘치면 그 줄을 자른다(예전과 같다)."""
    for cand in (line, line.split('. 반응이 가장 큰 글:')[0] if line else ''):
        text = '\n'.join(x for x in (first, cand) if x)
        if len(text) <= MEASURE_MAX:
            return text
    return first[:MEASURE_MAX]


def measure_line(today, counts=meta.post_counts):
    """게시하고 14~28일 지난 글 가운데 가장 최근 것의 판매 전후. 인과가 아니라 전후 비교다.
    전산망 실판매가 있으면 그것(전후 2주 부수), 없으면 알라딘 판매 지수. 올라간 곳(봇이 찾은 것)과 공식 글의 반응 수를 함께 적는다."""
    posted = (Draft.objects.filter(status=Draft.POSTED, posted_at__isnull=False, proposal__book__isnull=False)
              .select_related('proposal__book').order_by('-posted_at'))
    for d in posted:
        day = d.posted_at.astimezone(KST).date()
        if not (today - timedelta(days=28) <= day <= today - timedelta(days=14)):
            continue
        book = d.proposal.book
        letter = d.channel == Draft.LETTER
        verb = '보낸' if letter else '올린'
        sums = bnk_sales.around(book, day, today)
        if sums:
            sales = f'{"보내기" if letter else "올리기"} 전 2주 {sums[0]}권 → {verb} 뒤 2주 {sums[1]}권'
        else:
            before = latest(book, day)
            after = SalesSnapshot.objects.filter(book=book, date__gte=day + timedelta(days=14)).order_by('date').first()
            if not (before and after):
                continue
            sales = f'판매 지수 {before.sales_point} → {after.sales_point} (2주 뒤)'
        line = f'지난번 {verb} 『{book.title}』 글{_where(d)} ― {sales}'
        for part in _reactions(d, counts):
            line += f', {part}'
        clicks = _store_click_count(book, day)
        if clicks > 0:
            line += f', 사이트 서점 버튼 {clicks}번'
        return line
    return ''


def build_weekly(llm, today, now, posts, resolve=gnews.original_url, channel_line=channels.week_line):
    line = channel_line(today)   # 지난주 공식 채널 한 줄: 브리핑 끝(measure)과 LLM '참고' 블록에
    items, dropped = compose(llm, candidates.gather(today, now, posts), today,
                             candidates.social_context(now) + ([line] if line else []))
    for cand, *_ in items:  # 방에 보일 링크만(최대 4개): 구글 뉴스 주소는 언론사 원래 주소로, 실패하면 그대로
        if cand.link:
            cand.link = resolve(cand.link)
    briefing = save_briefing(items, today)
    briefing.measure = _fit_measure(measure_line(today), line)
    briefing.save(update_fields=['measure'])
    return briefing, dropped
