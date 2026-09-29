"""대화 기록에서 계기를 뽑는다 — 지난 기록 채우기와 프롬프트 시험. --dry-run 은 아무것도 쓰지 않고 화면에만 보여 준다.

개발자 컴퓨터에서 SSH 터널을 열고 MODE=dev(= 운영 DB)로 돌린다. 저장하면 넣은 기록에 표시(MomentScan)가 붙어
새벽 추출이 같은 기록을 다시 보지 않는다. 런북 .claude/docs/context/moments-runbook.md.
"""
from datetime import date, datetime, time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from intake.deps import build_deps
from marketing import moments
from marketing.timeutil import KST


def _day(value):
    try:
        return datetime.combine(date.fromisoformat(value), time.min, tzinfo=KST)
    except ValueError:
        raise CommandError(f'날짜 형식은 YYYY-MM-DD: {value}') from None


class Command(BaseCommand):
    help = '대화 기록에서 계기를 뽑는다(지난 기록 채우기·프롬프트 시험). --dry-run 은 아무것도 쓰지 않는다.'

    def add_arguments(self, parser):
        parser.add_argument('--since', required=True, help='이 날(KST 0시)부터의 기록, YYYY-MM-DD')
        parser.add_argument('--until', help='이 날(KST 0시) 전까지, YYYY-MM-DD')
        parser.add_argument('--dry-run', action='store_true', help='저장하지 않고 뽑은 결과만 보여 준다(노션·사진도 건너뜀)')
        parser.add_argument('--no-photos', action='store_true')
        parser.add_argument('--no-notion', action='store_true')
        parser.add_argument('--max-chunks', type=int, default=10, help='LLM 호출 수 상한(조각 하나 = 3만 자)')

    def handle(self, *args, **o):
        since, until = _day(o['since']), (_day(o['until']) if o['until'] else None)
        report = moments.daily(build_deps(), timezone.now(), since=since, until=until, notion=not o['no_notion'],
                               photos=not o['no_photos'], max_chunks=o['max_chunks'], dry_run=o['dry_run'])
        w = self.stdout.write
        w('미리보기(저장 안 함)' if o['dry_run'] else '저장함')
        if o['dry_run']:
            for text in report.preview:
                w(text)
        else:
            for s in report.new:
                w(('🔕 ' if s.sensitive else '+ ') + moments.signal_line(s))
            for text in report.changed:
                w('~ ' + text)
        for text in report.dropped:
            w('- 버림: ' + text)
        for text in report.errors:
            w('⚠️ ' + text)
        w(f'새 {len(report.new) or len([p for p in report.preview if p.startswith("+")])} · 바뀜 '
          f'{len(report.changed) or len([p for p in report.preview if p.startswith("~")])} · 버림 {len(report.dropped)} · '
          f'사진 {report.photos}장 · 노션 구역 {report.notion}개 · 남은 기록 {report.left}줄')
