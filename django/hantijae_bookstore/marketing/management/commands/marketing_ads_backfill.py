"""한티재 게시물 광고를 Meta 보관 기간(약 37개월) 전체로 한 번 채운다(배포 뒤 한 번, 서버에서).
출력은 개수·기간·합계만 — 다른 광고의 이름이나 숫자는 읽지도 찍지도 않는다. 오래전에 끝난 광고는 결과 카드 없이 둔다."""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from marketing import ads
from marketing.timeutil import kst_today


class Command(BaseCommand):
    help = '광고 성과 과거 채우기(한티재 게시물 광고만)'

    def handle(self, *args, **options):
        if not ads.configured():
            raise CommandError('광고 토큰 설정이 없어요(META_ADS_TOKEN 등)')
        today = kst_today(timezone.now())
        report = ads.collect(today, full=True)
        stale = ads.skip_stale(today)
        self.stdout.write(ads.report_text(report))
        self.stdout.write(f'{ads.saved_text()} · 카드 없이 둔 지난 광고 {stale}개')
