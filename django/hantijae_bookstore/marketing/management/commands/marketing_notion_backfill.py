"""이미 검수 방에 보낸 주간 브리핑을 노션 글 모음에 채워 넣고, 그 텔레그램 메시지 버튼(상황판·노션)을 다시 그린다.
스위치(marketing_notion)가 off여도 데이터 소스만 있으면 된다 — 켜기 전에 페이지를 먼저 확인하려고.

  --week YYYY-MM-DD   브리핑 주 시작(월요일)
  --dry-run           무엇을 만들지 출력만
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from intake.models import WorkerState
from marketing import board, messages, notion_sync
from marketing.management.commands.marketing_notion_setup import _clients
from marketing.models import Briefing


class Command(BaseCommand):
    help = '보낸 주간 브리핑을 노션 글 모음에 채워 넣기'

    def add_arguments(self, parser):
        parser.add_argument('--week', required=True)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, week, dry_run, **opts):
        b = Briefing.objects.filter(week_start=date.fromisoformat(week)).first()
        if not b or not (b.sent_at and b.message_id):
            raise CommandError('보낸 브리핑이 없어요')
        if not WorkerState.get(notion_sync.DS):
            raise CommandError('먼저 marketing_notion_setup 을 돌려 주세요')
        if not b.shown:  # 이 기능 전에 보낸 브리핑: 항목 전부(rank 순)
            b.shown = [p.id for p in b.items.order_by('rank', 'id')]
            if not dry_run:
                b.save(update_fields=['shown'])
        items = board.shown_items(b)
        target = notion_sync.brief_target(b, messages.briefing_text(b.week_start, items, b.measure, guide=False))
        if dry_run:
            self.stdout.write(target.name)
            for _, _, label in target.sections:
                self.stdout.write(f'  {label}')
            return
        client, tg = _clients()
        url = notion_sync.ensure_page(client, target, timezone.now())
        board.refresh(tg, board.briefing_hub(Briefing.objects.get(pk=b.pk)))
        self.stdout.write(f'만들었어요: {url}')
