from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.services import TelegramIdentityService


class TelegramIdentityServiceTests(TestCase):
    def test_find_allowed_user_returns_bound_active_user(self):
        user = get_user_model().objects.create_user(username="owner", password="password")
        TelegramIdentityService.bind_user(user=user, telegram_user_id=1001, chat_id=2002)

        found_user = TelegramIdentityService.find_allowed_user(telegram_user_id=1001)

        self.assertEqual(found_user, user)

    def test_find_allowed_user_ignores_unknown_telegram_id(self):
        found_user = TelegramIdentityService.find_allowed_user(telegram_user_id=9999)

        self.assertIsNone(found_user)

