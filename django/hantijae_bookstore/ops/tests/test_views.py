from django.contrib.auth import get_user_model
from django.test import TestCase

from intake.models import WorkerState


class StatusPageTest(TestCase):
    URL = '/ops/status'

    def login(self, **flags):
        user = get_user_model().objects.create_user('someone', password='pw', **flags)
        self.client.force_login(user)
        return user

    def test_anonymous_visitor_is_sent_to_admin_login(self):
        res = self.client.get(self.URL)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res['Location'].startswith('/admin/login/'))
        self.assertIn('next=/ops/status', res['Location'])

    def test_logged_in_non_staff_is_sent_to_admin_login(self):
        self.login()
        res = self.client.get(self.URL)
        self.assertEqual(res.status_code, 302)
        self.assertTrue(res['Location'].startswith('/admin/login/'))

    def test_staff_sees_the_page_uncached_and_unindexed(self):
        self.login(is_staff=True)
        WorkerState.put('marketing_mode', 'live')
        res = self.client.get(self.URL)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '독자 서평')
        self.assertContains(res, '살펴볼 것')
        self.assertIn('no-cache', res['Cache-Control'])
        self.assertEqual(res['X-Robots-Tag'], 'noindex, nofollow')

    def test_page_never_shows_unlisted_state_values(self):
        self.login(is_staff=True)
        WorkerState.put('marketing_notion_db', 'notion-db-secret-id')
        self.assertNotContains(self.client.get(self.URL), 'notion-db-secret-id')
