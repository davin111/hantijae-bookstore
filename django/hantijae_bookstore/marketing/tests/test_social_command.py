import json
import tempfile
from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from marketing.models import Signal, SocialPost, SocialRun
from marketing.tests.fakes import SOCIAL_ACCOUNTS, FakeLLM, fb_item

SETTINGS = {'APIFY_TOKEN': '', 'SOCIAL_ACCOUNTS': json.dumps(SOCIAL_ACCOUNTS)}


@override_settings(MARKETING=SETTINGS)
class SocialCommandTest(TestCase):
    def run_file(self, *extra):
        items = [fb_item('1', text='『무지개를 변호하다』 북토크 10월 12일', time='2026-09-29T02:35:04.000Z')]
        llm = FakeLLM({'items': [{'id': 0, 'relevant': True, 'private': False, 'sensitive': False, 'category': 'event',
                                  'books': [], 'event': {'date': '2026-10-12', 'name': '북토크', 'place': ''},
                                  'summary': '북토크 안내'}]})
        out = StringIO()
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(items, f)
        with mock.patch('marketing.management.commands.marketing_social.build_deps',
                        return_value=SimpleNamespace(llm=llm, bot=SimpleNamespace(notify_admin=print))), \
                mock.patch('marketing.management.commands.marketing_social.timezone.now',
                           return_value=datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)):
            call_command('marketing_social', '--from-file', f.name, '--platform', 'facebook', *extra, stdout=out)
        return out.getvalue()

    def test_from_file_dry_run_saves_nothing(self):
        out = self.run_file('--dry-run')
        self.assertIn('새 글 1건, 관련 신호 1개', out)
        self.assertIn('sns 후보 종류:', out)
        self.assertIn('dry-run: 저장하지 않았어요', out)
        self.assertEqual((SocialPost.objects.count(), Signal.objects.count(), SocialRun.objects.count()), (0, 0, 0))

    def test_from_file_saves_without_dry_run(self):
        self.run_file()
        self.assertEqual((SocialPost.objects.count(), Signal.objects.count()), (1, 1))

    def test_status(self):
        out = StringIO()
        call_command('marketing_social', '--status', stdout=out)
        self.assertIn('social=off', out.getvalue())
        self.assertIn('social_missing=APIFY_TOKEN', out.getvalue())
