import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.config import get_settings
from app.db.database import init_db
from app.services.telegram_callback import _submit_telegram_update, handle_telegram_update


class TelegramCallbackTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.tempdir.name) / "test.db"),
                "TELEGRAM_ENABLED": "true",
                "TELEGRAM_BOT_TOKEN": "bot-token",
                "TELEGRAM_CHAT_ID": "-100123",
            },
        )
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    @patch("app.services.telegram_callback.answer_telegram_callback")
    @patch("app.services.telegram_callback.handle_command")
    def test_button_callback_is_forwarded_as_command(self, handle_command, answer_callback):
        handle_telegram_update(
            {
                "update_id": 100,
                "callback_query": {
                    "id": "callback-1",
                    "data": "mi:choice:2",
                    "message": {"chat": {"id": -100123}},
                },
            },
            "https://media.example",
        )

        handle_command.assert_called_once_with("2", "-100123", "https://media.example")
        answer_callback.assert_called_once_with("callback-1")

    @patch("app.services.telegram_callback.handle_command")
    def test_text_message_is_forwarded_from_configured_chat(self, handle_command):
        handle_telegram_update(
            {
                "update_id": 101,
                "message": {"text": "蜘蛛侠：英雄无归", "chat": {"id": -100123}},
            }
        )

        handle_command.assert_called_once_with("蜘蛛侠：英雄无归", "-100123", "")

    def test_updates_are_submitted_to_bounded_executor(self):
        executor = Mock()
        update = {"update_id": 102}
        with patch("app.services.telegram_callback._UPDATE_EXECUTOR", executor):
            self.assertTrue(_submit_telegram_update(update))
        executor.submit.assert_called_once_with(handle_telegram_update, update, "")

    @patch("app.services.telegram_callback.process_channel_post")
    def test_channel_posts_use_the_independent_resource_source_switch(self, process_channel_post):
        update = {"update_id": 103, "channel_post": {"message_id": 7, "chat": {"id": -100999}, "text": "Movie"}}

        handle_telegram_update(update)
        process_channel_post.assert_not_called()

        with patch.dict(os.environ, {"TELEGRAM_CHANNEL_SOURCE_ENABLED": "true"}):
            get_settings.cache_clear()
            handle_telegram_update(update)

        process_channel_post.assert_called_once_with(update["channel_post"])
