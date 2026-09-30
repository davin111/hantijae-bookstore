"""노션 '홍보 비서 글 모음' 데이터베이스를 한 번 만든다(이미 있으면 그대로).

  --parent <페이지 id>   만들 곳(예: '마케팅 관련 자료' dd737f5da23340c29dc270ba981d5c1b)
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from intake.models import WorkerState
from intake.notion import NotionClient
from intake.telegram_api import TelegramAPI
from marketing import notion_blocks as nb
from marketing import notion_sync


def _clients():
    c = settings.INTAKE
    if not c.get('NOTION_TOKEN'):
        raise CommandError('NOTION_TOKEN 이 없어요')
    return NotionClient(c['NOTION_TOKEN']), TelegramAPI(c['TELEGRAM_BOT_TOKEN'])


class Command(BaseCommand):
    help = "노션 '홍보 비서 글 모음' 데이터베이스 만들기"

    def add_arguments(self, parser):
        parser.add_argument('--parent', required=True)

    def handle(self, *args, parent, **opts):
        if WorkerState.get(notion_sync.DS):
            self.stdout.write(f'이미 있어요: data_source={WorkerState.get(notion_sync.DS)}')
            return
        client, _ = _clients()
        db = client.create_database(parent, nb.DB_TITLE, nb.DB_PROPERTIES)
        WorkerState.put(notion_sync.DS, db['data_sources'][0]['id'])
        WorkerState.put('marketing_notion_db', db['id'])
        self.stdout.write(f"만들었어요: {db.get('url', db['id'])} (data_source={db['data_sources'][0]['id']})")
