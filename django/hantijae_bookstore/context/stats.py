"""관리자 /ctx 에 보여 줄 요약. 관리자 1:1 방용이라 기술 용어를 써도 된다."""
from collections import Counter
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Count

from context.models import DEFAULT_ROLE, ContextEntry
from context.redact import LABELS

KST = ZoneInfo('Asia/Seoul')


def _kst(dt):
    return dt.astimezone(KST).strftime('%Y-%m-%d %H:%M') if dt else '-'


def summary_lines(now):
    qs = ContextEntry.objects.filter(forgotten=False)
    total = qs.count()
    lines = [f"보관 {settings.CONTEXT['RETENTION_DAYS']}일 · 기록 {total:,}건"]
    if not total:
        return lines
    oldest = qs.order_by('at').values_list('at', flat=True).first()
    first_live = qs.filter(origin=ContextEntry.LIVE).order_by('at').values_list('at', flat=True).first()
    lines.append(f'가장 오래된 기록 {_kst(oldest)} · 실시간 시작 {_kst(first_live)}')
    counts = Counter()
    for r in qs.filter(at__gte=now - timedelta(days=7)).values_list('redactions', flat=True):
        counts.update(r or {})
    if counts:
        lines.append('최근 7일 가림: ' + ' · '.join(f'{LABELS[k]} {n}' for k, n in counts.most_common()))
    unknown = (qs.filter(role=DEFAULT_ROLE).values('author_id', 'author_name')
               .annotate(n=Count('id')).order_by('-n')[:10])
    if unknown:
        lines.append('역할 없는 사람: ' + ', '.join(
            f"{u['author_name'] or '?'}({u['author_id'] or '내보내기'}) {u['n']}건" for u in unknown))
    return lines
