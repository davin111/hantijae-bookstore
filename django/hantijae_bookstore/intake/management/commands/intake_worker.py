from django.core.management.base import BaseCommand

from intake.deps import build_deps
from intake.pipeline import recover_interrupted, run_iteration


class Command(BaseCommand):
    help = '신간 등록 자동화 워커 (텔레그램 롱폴링 + 드라이브 폴링)'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='한 번만 돌고 종료 (점검용)')

    def handle(self, *args, **options):
        deps = build_deps()
        # 처리 도중 죽었던 자료는 다시 대기열로 (여러 번 죽은 자료는 실패 처리)
        recover_interrupted(deps)
        while True:
            run_iteration(deps)
            if options['once']:
                break
