from unittest import TestCase
from unittest.mock import MagicMock

from bot.services.telegram_download import (
    TELEGRAM_BOT_DOWNLOAD_LIMIT_BYTES,
    extract_media_payload,
    is_file_too_large_for_standard_api,
)


class ExtractMediaPayloadTests(TestCase):
    def _empty_message(self, message_id: int = 1) -> MagicMock:
        message = MagicMock()
        message.message_id = message_id
        message.photo = None
        message.video = None
        message.animation = None
        message.audio = None
        message.voice = None
        message.document = None
        return message

    def test_extracts_audio_track(self):
        message = self._empty_message(42)
        message.audio = MagicMock(
            file_id="audio-id",
            file_name="track.mp3",
            mime_type="audio/mpeg",
            file_size=4096,
        )

        payload = extract_media_payload(message)

        self.assertIsNotNone(payload)
        self.assertEqual(payload.file_id, "audio-id")
        self.assertEqual(payload.original_name, "track.mp3")
        self.assertEqual(payload.mime_type, "audio/mpeg")
        self.assertEqual(payload.file_size, 4096)

    def test_extracts_voice_message(self):
        message = self._empty_message(7)
        message.voice = MagicMock(
            file_id="voice-id",
            mime_type="audio/ogg",
            file_size=2048,
        )

        payload = extract_media_payload(message)

        self.assertIsNotNone(payload)
        self.assertEqual(payload.file_id, "voice-id")
        self.assertEqual(payload.original_name, "telegram_voice_7.ogg")
        self.assertEqual(payload.mime_type, "audio/ogg")
        self.assertEqual(payload.file_size, 2048)

    def test_is_file_too_large_for_standard_api(self):
        limit = TELEGRAM_BOT_DOWNLOAD_LIMIT_BYTES
        self.assertFalse(is_file_too_large_for_standard_api(None))
        self.assertFalse(is_file_too_large_for_standard_api(limit))
        self.assertTrue(is_file_too_large_for_standard_api(limit + 1))
