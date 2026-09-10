"""Regression coverage: existing owner keeps access, strangers cannot claim MAX."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456789:" + "A" * 35)
os.environ.setdefault("ALLOWED_CHAT_ID", "123456789")

from bot.max_bot import MaxBot
from bot.security import AuthMiddleware


class AccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_max_chat_survives_restart_without_user_id(self):
        bot = MaxBot("test")
        bot.owner_chat_id = "42"
        self.assertFalse(await bot._learn_owner("99", "attacker"))
        self.assertIsNone(bot._owner_user_id)
        self.assertTrue(await bot._learn_owner("42", "owner"))
        self.assertFalse(await bot._learn_owner("99", "owner"))

    async def test_missing_chat_or_binding_fails_closed(self):
        bot = MaxBot("test")
        self.assertFalse(await bot._learn_owner("42", "owner"))
        bot.owner_chat_id = "42"
        self.assertFalse(await bot._learn_owner(None, "owner"))

    async def test_foreign_start_never_sends(self):
        bot = MaxBot("test")
        bot.owner_chat_id = "42"
        with patch.object(bot, "_send_to", new_callable=AsyncMock) as send:
            await bot._on_started({"chat_id": 99, "user": {"user_id": 99}})
            send.assert_not_awaited()

    async def test_callback_requires_actual_chat_and_accepts_top_level_message(self):
        bot = MaxBot("test")
        bot.owner_chat_id = "42"
        with patch.object(bot, "_answer_cb", new_callable=AsyncMock) as answer:
            await bot._on_callback({"payload": "morning:later", "user": {"user_id": 99}})
            answer.assert_not_awaited()
        with patch.object(bot, "_on_callback", new_callable=AsyncMock) as callback:
            await bot._dispatch({"update_type": "message_callback", "callback": {"callback_id": "x"}, "message": {"recipient": {"chat_id": 42}}})
            self.assertEqual(callback.call_args.args[0]["message"]["recipient"]["chat_id"], 42)

    async def test_telegram_messages_and_callbacks(self):
        auth = AuthMiddleware(42)
        for callback in (False, True):
            for user_id, kind, allowed in ((42, "private", True), (99, "private", False), (42, "group", False)):
                chat = SimpleNamespace(id=42, type=kind)
                event = SimpleNamespace(from_user=SimpleNamespace(id=user_id))
                if callback:
                    event.message = SimpleNamespace(chat=chat)
                else:
                    event.chat = chat
                handler = AsyncMock()
                await auth(handler, event, {})
                self.assertEqual(handler.await_count, int(allowed))


if __name__ == "__main__":
    unittest.main()
