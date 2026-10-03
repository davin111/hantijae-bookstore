from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from marketing.timeutil import KST
from ops import health

WEEKDAYS = '월화수목금토일'


@never_cache
@staff_member_required   # 로그인하지 않았거나 staff가 아니면 /admin/login/?next=… 으로 보낸다
def status(request):
    """운영 상태 — 열 때마다 DB에서 새로 계산한다(읽기만 한다. 다시 돌리기는 텔레그램 /fund now 등)."""
    now = timezone.now()
    local = now.astimezone(KST)
    rows = health.evaluate(now)
    daily = [r for r in rows if r.group == 'daily']
    hm = f'{local:%H:%M}'
    counts = {s: sum(r.state == s for r in rows) for s in health.LABELS}
    response = render(request, 'ops/status.html', {
        'checked_at': f'{local:%Y-%m-%d} ({WEEKDAYS[local.weekday()]}) {hm} KST',
        'now_hm': hm,
        'daily': daily,
        'now_index': next((i for i, r in enumerate(daily) if r.when > hm), len(daily)),
        'always': [r for r in rows if r.group == 'always'],
        'warn': health.watch(rows),
        'upcoming': [r for r in rows if r.state == health.WAIT],
        'counts': counts,
        'total': len(rows),
        'labels': health.LABELS,
        'grace_minutes': int(health.GRACE.total_seconds() // 60),
    })
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response
