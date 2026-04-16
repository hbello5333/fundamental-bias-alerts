from __future__ import annotations

import unittest

from fundamental_bias_alerts.telegram import extract_recent_chats


class TelegramHelpersTests(unittest.TestCase):
    def test_extract_recent_chats_deduplicates_and_formats_names(self) -> None:
        chats = extract_recent_chats(
            [
                {
                    "update_id": 1,
                    "message": {
                        "chat": {
                            "id": 123,
                            "type": "private",
                            "first_name": "Henry",
                            "last_name": "Bell",
                            "username": "henrybell",
                        }
                    },
                },
                {
                    "update_id": 2,
                    "edited_message": {
                        "chat": {
                            "id": 123,
                            "type": "private",
                            "first_name": "Henry",
                            "last_name": "Bell",
                            "username": "henrybell",
                        }
                    },
                },
                {
                    "update_id": 3,
                    "channel_post": {
                        "chat": {
                            "id": -1001,
                            "type": "channel",
                            "title": "Macro Alerts",
                            "username": "macro_alerts",
                        }
                    },
                },
            ]
        )

        self.assertEqual(len(chats), 2)
        self.assertEqual(chats[0]["chat_id"], -1001)
        self.assertEqual(chats[0]["display_name"], "Macro Alerts")
        self.assertEqual(chats[1]["display_name"], "Henry Bell")
