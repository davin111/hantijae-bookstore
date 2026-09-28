"""진행 중인 한티재 북펀드의 진척. 펀딩 감지는 intake(FundingCampaign)가 하고, 여기서는 기록된 펀딩만 읽는다."""
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from intake.models import FundingCampaign
from marketing.http import http_get
from marketing.models import FundingSnapshot
from marketing.timeutil import KST

_PROGRESS = re.compile(r'class="price_t">([0-9,]+)</span>원,\s*([0-9,]+)권 펀딩\s*/\s*목표 금액\s*([0-9,]+)원')


@dataclass
class Progress:
    amount: int
    goal: int
    books: int


def _n(s):
    return int(s.replace(',', ''))


def parse_aladin_progress(html) -> Optional[Progress]:
    m = _PROGRESS.search(html or '')
    return Progress(amount=_n(m.group(1)), books=_n(m.group(2)), goal=_n(m.group(3))) if m else None


def live_campaigns(now):
    return FundingCampaign.objects.filter(is_ours=True, ends_at__gt=now).order_by('ends_at')


def ends_on(campaign):
    """ends_at은 마감일 다음 날 0시(KST)다."""
    return (campaign.ends_at.astimezone(KST) - timedelta(seconds=1)).date()


def collect_funding(today, now, get=http_get):
    """진행 중인 알라딘 북펀드의 오늘 진척을 저장한다. 텀블벅은 v1에서 진척을 읽지 않는다."""
    saved = 0
    for camp in live_campaigns(now).filter(platform='aladin'):
        try:
            p = parse_aladin_progress(get(camp.url))
        except Exception:
            p = None
        if p is None:
            continue
        FundingSnapshot.objects.update_or_create(campaign=camp, date=today,
                                                 defaults={'amount': p.amount, 'goal': p.goal, 'books': p.books})
        saved += 1
    return saved


def is_stalled(campaign, today, days=3, threshold=0.02):
    now_snap = campaign.snapshots.filter(date__lte=today).order_by('-date').first()
    before = campaign.snapshots.filter(date__lte=today - timedelta(days=days)).order_by('-date').first()
    if not now_snap or not before or not now_snap.amount:
        return False
    return (now_snap.amount - before.amount) < now_snap.amount * threshold
