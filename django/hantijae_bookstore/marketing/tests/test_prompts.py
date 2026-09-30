from types import SimpleNamespace

from django.test import SimpleTestCase

from marketing.prompts import build_rewrite_user


class RewritePromptTest(SimpleTestCase):
    def test_letter_places_are_given_as_reference_only(self):
        d = SimpleNamespace(label='보낼 글', title='부탁', body='안녕하세요.', extra={'places': ['농민회']})
        text = build_rewrite_user(d, '정중하게', '')
        self.assertIn('<보낼 곳(참고만, 바꾸지 않음)>\n농민회\n</보낼 곳(참고만, 바꾸지 않음)>', text)
        plain = SimpleNamespace(label='인스타 글', title='', body='글', extra={})
        self.assertNotIn('보낼 곳', build_rewrite_user(plain, '짧게', ''))
