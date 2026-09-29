"""주간 브리핑: 후보를 LLM에 한 번 보내 최대 3개를 고르게 하고, 코드로 다시 검증한다."""
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from intake.llm import complete_json
from marketing import candidates
from marketing.models import Briefing, Draft, Proposal, SalesSnapshot, Signal
from marketing.prompts import BRIEFING_SYSTEM, build_briefing_user
from marketing.sales import latest
from marketing.text import fix_title_marks, foreign_numbers
from marketing.timeutil import KST, week_start
from web.models import StoreClick

MAX_ITEMS = 3
SALES_WORDS = ('구매', '주문', '할인', '서점에서', '링크', 'http', '가격')
CHANNELS = (Draft.INSTAGRAM, Draft.BLOG, Draft.LETTER)


def compose(llm, cands, today, midweek=False):
    if not cands:
        return [], []
    by_id = {c.id: c for c in cands}
    result = complete_json(llm, BRIEFING_SYSTEM, build_briefing_user(cands, today, midweek=midweek))
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
        bad = foreign_numbers(' '.join([headline, reason, body]), cand.allowed_texts() + [today.isoformat()])
        if bad:
            dropped.append(f'{cand.id}: 자료에 없는 숫자 {", ".join(bad)}')
            continue
        if cand.memorial and any(w in ' '.join([headline, reason, body]) for w in SALES_WORDS):
            dropped.append(f'{cand.id}: 추모 성격의 날에 판매 권유')
            continue
        ids = {b.id for b in cand.books}
        if ids & used_books:
            dropped.append(f'{cand.id}: 같은 책이 이미 있음')
            continue
        used_books |= ids
        channel = d.get('channel') if d.get('channel') in CHANNELS else Draft.INSTAGRAM
        items.append((cand, headline, reason,
                      {'channel': channel, 'title': fix_title_marks(str(d.get('title', '')).strip()), 'body': body}))
        if len(items) == MAX_ITEMS:
            break
    return items, dropped


def save_briefing(items, today):
    with transaction.atomic():  # 도중에 실패하면 옛 항목이 그대로 남는다(반쯤 만든 브리핑이 나가지 않게)
        briefing, _ = Briefing.objects.get_or_create(week_start=week_start(today))
        # 관리자가 /brief 로 다시 만들면 새 항목으로 바꾼다. 옛 항목이 쓴 저자 소식은 다시 후보가 되게 풀어 준다
        Signal.objects.filter(proposal__briefing=briefing).update(used_at=None)
        briefing.items.all().delete()
        for rank, (cand, headline, reason, d) in enumerate(items, 1):
            p = Proposal.objects.create(kind=Proposal.BRIEF_ITEM, book=cand.books[0] if cand.books else None,
                                        signal=cand.signal, briefing=briefing, candidate_key=cand.id,
                                        headline=headline[:300], reason=reason, rank=rank)
            Draft.objects.create(proposal=p, channel=d['channel'], title=d['title'][:300], body=d['body'])
            if cand.signal:
                Signal.objects.filter(pk=cand.signal.pk).update(used_at=timezone.now())
    return briefing


def _store_click_count(book, day):
    start = datetime.combine(day, datetime.min.time(), tzinfo=KST)
    end = start + timedelta(days=14)
    return StoreClick.objects.filter(book=book, created_at__gte=start, created_at__lt=end).count()


def measure_line(today):
    """게시하고 14~28일 지난 글 가운데 가장 최근 것의 판매 지수 전후. 인과가 아니라 전후 비교다."""
    posted = (Draft.objects.filter(status=Draft.POSTED, posted_at__isnull=False, proposal__book__isnull=False)
              .select_related('proposal__book').order_by('-posted_at'))
    for d in posted:
        day = d.posted_at.astimezone(KST).date()
        if not (today - timedelta(days=28) <= day <= today - timedelta(days=14)):
            continue
        book = d.proposal.book
        before = latest(book, day)
        after = SalesSnapshot.objects.filter(book=book, date__gte=day + timedelta(days=14)).order_by('date').first()
        if before and after:
            line = f'지난번 올린 『{book.title}』 {d.label} ― 판매 지수 {before.sales_point} → {after.sales_point} (2주 뒤)'
            clicks = _store_click_count(book, day)
            if clicks > 0:
                line += f', 사이트 서점 버튼 {clicks}번'
            return line
    return ''


def build_weekly(llm, today, now, posts):
    items, dropped = compose(llm, candidates.gather(today, now, posts), today)
    briefing = save_briefing(items, today)
    briefing.measure = measure_line(today)[:300]
    briefing.save(update_fields=['measure'])
    return briefing, dropped
