"""공공 선정 발표를 지금 한 번 확인한다(운영 점검·첫 배포 확인용).
--dry-run: 읽고 대조한 결과만 보여 주고 기록·알림은 하지 않는다(트랜잭션을 되돌린다)."""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from marketing import selections
from marketing.timeutil import kst_today


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = '공공 선정 발표 확인 (--dry-run이면 기록하지 않음)'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, dry_run=False, **options):
        now = timezone.now()
        today = kst_today(now)
        if dry_run:
            try:
                with transaction.atomic():
                    found, failed = selections.collect(today)
                    self._report(found, failed)
                    raise _Rollback
            except _Rollback:
                self.stdout.write('(dry-run: 기록하지 않았어요)')
            return
        from intake.deps import build_deps
        self._report(selections.run_scan(build_deps(), today, now), [])

    def _report(self, found, failed):
        self.stdout.write(f'찾은 책 {len(found)}건, 읽지 못한 출처 {", ".join(failed) or "없음"}')
        for f in found:
            a = f.announcement
            self.stdout.write(f'- {a.label} | 『{f.signal.book.title}』 | {f.how} | '
                              f'새 발표={a.fresh} 철회={a.withdrawal} | {a.url}')
