import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456789:" + "A" * 35)
os.environ.setdefault("ALLOWED_CHAT_ID", "123456789")

from bot import db, messages
from bot.bot_session import build_bot
from bot.scheduler import BotScheduler
from aiogram.enums import ParseMode


class BotSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_progress_and_duplicate_delivery_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            await db.init_db(str(Path(directory) / "test.db"))
            try:
                state = await db.get_state()
                self.assertEqual(state["current_day"], 1)
                await db.update_state(current_day=7)
                self.assertEqual((await db.get_state())["current_day"], 7)
                self.assertFalse(await db.was_sent("2026-09-08", "morning"))
                await db.mark_sent("2026-09-08", "morning")
                await db.mark_sent("2026-09-08", "morning")
                self.assertTrue(await db.was_sent("2026-09-08", "morning"))
                await db.set_channel("max", chat_id="42")
                self.assertEqual(await db.get_chat_id("max"), "42")
            finally:
                await db.close_db()

    async def test_sdk_and_all_thirty_days(self):
        for proxy in (None, "socks5://127.0.0.1:1080", "http://127.0.0.1:1080"):
            bot = build_bot("123456789:" + "A" * 35, proxy=proxy, parse_mode=ParseMode.MARKDOWN)
            try:
                BotScheduler(bot, 42)  # No polling or scheduler start, no network writes.
                for day in range(1, 31):
                    text, keyboard = messages.morning_text(day, "https://example.org/test")
                    self.assertTrue(text)
                    self.assertTrue(keyboard.inline_keyboard)
            finally:
                await bot.session.close()
