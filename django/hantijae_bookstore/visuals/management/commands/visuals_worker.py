import fcntl
import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from intake.telegram_api import TelegramAPI
from visuals.assets import root
from visuals.client import VisualClient
from visuals.pipeline import run_once

log = logging.getLogger('intake')


class Command(BaseCommand):
    help = '홍보 이미지 제작·전달 (텔레그램 수신 워커와 분리)'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        root().mkdir(parents=True, exist_ok=True)
        with (root() / '.worker.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CommandError('이미지 워커가 이미 실행 중입니다') from exc
            c = settings.INTAKE
            llm = VisualClient(c['SIDECAR_URL'], c['SIDECAR_TOKEN'], c['SIDECAR_MODEL'], timeout=300)
            tg = TelegramAPI(c['TELEGRAM_BOT_TOKEN'])
            while True:
                close_old_connections()
                try:
                    run_once(llm, tg)
                except Exception:
                    log.exception('visuals worker iteration failed')
                    if options['once']:
                        raise
                if options['once']:
                    break
                time.sleep(30)
