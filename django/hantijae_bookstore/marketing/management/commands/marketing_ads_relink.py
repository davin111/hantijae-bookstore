"""책이 빈 광고를 지금 다시 맞춘다(배포 뒤 한 번·운영 점검). 글자 맞추기(사이트 도서 + 사이트에 없는 북펀드 책)를 하고,
그래도 못 찾았고 아직 묻지 않은 광고는 AI에게 한 번 묻는다(--no-ai면 묻지 않는다). 매일 06:50 수집 뒤에도 같은 일을 한다."""
from django.core.management.base import BaseCommand

from marketing import ad_books, ads
from marketing.models import Ad


class Command(BaseCommand):
    help = '광고 글의 책 다시 맞추기(글자 맞추기 + AI 한 번)'

    def add_arguments(self, parser):
        parser.add_argument('--no-ai', action='store_true')

    def handle(self, *args, no_ai=False, **options):
        llm = None
        if not no_ai:
            from intake.deps import build_deps
            llm = build_deps().llm
        result = ad_books.relink(llm)
        self.stdout.write(f'책·제목을 새로 정한 광고 {result.linked}개 · AI에게 물은 광고 {result.asked}개 · '
                          f'AI 오류 {result.failed}개(다음에 다시)')
        for ad in Ad.objects.filter(pk__in=result.changed).select_related('book').order_by('-last_day'):
            when = ads.period(ad.first_day, ad.last_day) if ad.first_day else '날짜 없음'
            self.stdout.write(f'· {ads.name(ad)} {when}')
