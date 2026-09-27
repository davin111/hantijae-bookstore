"""가족방에 '확인 부탁' 묶음을 보낸다.

JSON: {"batch": 이름, "intro": 첫 안내문(선택),
       "items": [{"book_id", "notion_page_id", "title", "body", "options": [{"label", "set": {항목: 값}}],
                  "expect": {항목: {"notion": 값, "site": 값}}}]}
expect 는 조사할 때 본 값이다. 지금 값과 다르면(그사이 누가 고침) 그 항목은 보내지 않는다.
"""
import json
import time

from django.core.management.base import BaseCommand

from intake import messages, review
from intake.deps import build_deps
from intake.models import ReviewItem
from intake.telegram_api import TelegramError

PAUSE = 3.5   # 텔레그램은 그룹방에 봇 메시지를 분당 20개까지만 허용한다


class Command(BaseCommand):
    help = "가족방에 확인 부탁 묶음을 보낸다 (JSON 파일)"

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--dry-run', action='store_true', help='보내지 않고 문구만 출력')

    def _send(self, tg, chat, text, buttons=None):
        try:
            return tg.send_message(chat, text, buttons=buttons)
        except TelegramError as e:
            if 'Too Many Requests' not in str(e):
                raise
            time.sleep(40)
            return tg.send_message(chat, text, buttons=buttons)

    def handle(self, path, dry_run=False, **options):
        with open(path, encoding='utf-8') as fh:
            spec = json.load(fh)
        deps = build_deps()
        accepted = []
        for s in spec['items']:
            before = review.snapshot(s.get('book_id'), s.get('notion_page_id', ''), review.fields_of(s), deps.notion)
            if s.get('expect') is not None and review.normalize_snapshot(s['expect']) != before:
                self.stdout.write(f"건너뜀(값이 바뀜): {s['title']} 예상={s['expect']} 현재={before}")
                continue
            accepted.append((s, before))
        total = len(accepted)
        if dry_run:
            if spec.get('intro'):
                self.stdout.write(spec['intro'] + '\n---')
            for i, (s, _) in enumerate(accepted, 1):
                item = ReviewItem(seq=i, title=s['title'], body=s.get('body', ''), options=s['options'])
                self.stdout.write(messages.review_text(item, total))
                self.stdout.write('  버튼: ' + ' | '.join(o['label'] for o in s['options']) + '\n---')
            return
        chat = deps.bot.review_chat_id()
        items = [review.create_item(spec['batch'], i, s, deps.notion, before=before)
                 for i, (s, before) in enumerate(accepted, 1)]
        if spec.get('intro'):
            self._send(deps.tg, chat, spec['intro'])
            time.sleep(PAUSE)
        for item in items:
            sent = self._send(deps.tg, chat, messages.review_text(item, total), messages.review_buttons(item))
            ReviewItem.objects.filter(pk=item.pk).update(chat_id=chat, message_id=sent['message_id'])
            time.sleep(PAUSE)
        self.stdout.write(f'{total}건 보냄 → chat {chat}')
