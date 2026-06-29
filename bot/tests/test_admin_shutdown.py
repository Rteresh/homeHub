import os
import unittest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "homehub.settings")

import django

django.setup()

from bot.routers.album import SHUTDOWN_BUTTON, main_keyboard


class MainKeyboardAdminTest(unittest.TestCase):
    def test_shutdown_button_only_for_bot_admin(self) -> None:
        admin_texts = {button.text for row in main_keyboard(is_bot_admin=True).keyboard for button in row}
        user_texts = {button.text for row in main_keyboard(is_bot_admin=False).keyboard for button in row}

        self.assertIn(SHUTDOWN_BUTTON, admin_texts)
        self.assertNotIn(SHUTDOWN_BUTTON, user_texts)


if __name__ == "__main__":
    unittest.main()
