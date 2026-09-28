from django.core.management.base import BaseCommand

from marketing.hooks import seed


class Command(BaseCommand):
    help = '기념일 초기 목록 넣기(여러 번 실행해도 됨)'

    def handle(self, *args, **options):
        created, missing = seed()
        self.stdout.write(f'새 기념일 {created}개')
        if missing:
            self.stdout.write('사이트에서 찾지 못한 책: ' + ', '.join(sorted(set(missing))))
