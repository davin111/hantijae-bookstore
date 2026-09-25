import json
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from intake.bot import Bot
from intake.drive import DriveClient, DriveOpsImpl
from intake.llm import SidecarClient
from intake.notion import NotionClient
from intake.telegram_api import TelegramAPI


@dataclass
class Deps:
    tg: Any
    llm: Any
    bot: Any
    drive: Any = None
    notion: Any = None
    drive_root: str = ''


def build_deps(config=None):
    c = config or settings.INTAKE
    tg = TelegramAPI(c['TELEGRAM_BOT_TOKEN'])
    llm = SidecarClient(c['SIDECAR_URL'], c['SIDECAR_TOKEN'], c['SIDECAR_MODEL'])
    drive = DriveClient(json.loads(c['GOOGLE_SERVICE_ACCOUNT_JSON'])) if c.get('GOOGLE_SERVICE_ACCOUNT_JSON') else None
    notion = NotionClient(c['NOTION_TOKEN']) if c.get('NOTION_TOKEN') else None
    drive_ops = DriveOpsImpl(drive, c['DRIVE_ROOT_FOLDER_ID']) if drive else None
    bot = Bot(tg, llm, notion=notion, drive_ops=drive_ops, config=c)
    return Deps(tg=tg, llm=llm, bot=bot, drive=drive, notion=notion, drive_root=c.get('DRIVE_ROOT_FOLDER_ID', ''))
