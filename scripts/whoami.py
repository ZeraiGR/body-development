"""Узнать свой chat_id через твоего же бота (без ALLOWED_CHAT_ID).

Замкнутый круг: главный бот требует ALLOWED_CHAT_ID при старте, а id узнать
неизвестно. Этот скрипт ломает круг — он запускает бота в «режиме выдачи id»
без авторизации и просто отвечает числом.

Если Telegram API заблокирован в сети (timeout на getMe) — пропиши в .env
переменную TG_PROXY (http://host:port или socks5://host:port).

Использование:
    1. Впиши в .env настоящий BOT_TOKEN (от @BotFather) и, при необходимости, TG_PROXY.
    2. python3 scripts/whoami.py
    3. Напиши своему боту ЛЮБОЕ сообщение (текст, /start, стикер).
    4. Он ответит числом — это твой chat_id. Скопируй в .env:
           ALLOWED_CHAT_ID=<это число>
    5. Ctrl+C, затем запускай основной бот: python3 main.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from aiogram import Dispatcher
from aiogram.types import Message

from bot.bot_session import build_bot

PLACEHOLDER = "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


async def main() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        print("❌ В .env не задан BOT_TOKEN. Получи токен у @BotFather и впиши его.")
        return
    if token == PLACEHOLDER:
        print("❌ В .env всё ещё стоит токен-заглушка. Замени его на настоящий от @BotFather.")
        return

    proxy = os.getenv("TG_PROXY", "").strip() or None
    bot = build_bot(token, proxy=proxy)
    dp = Dispatcher()

    @dp.message()
    async def reveal(msg: Message) -> None:
        chat_id = msg.chat.id
        user_id = msg.from_user.id if msg.from_user else None
        username = msg.from_user.username if msg.from_user else None
        print(f"==> chat_id={chat_id}  user_id={user_id}  username=@{username}")
        await msg.answer(
            f"✅ Твой chat_id:\n\n{chat_id}\n\n"
            f"Скопируй это число в .env:\n"
            f"ALLOWED_CHAT_ID={chat_id}\n\n"
            f"Затем нажми Ctrl+C и запусти основной бот: python3 main.py"
        )

    via = f" через прокси {proxy}" if proxy else " напрямую (без прокси)"
    print(f"Подключаюсь к Telegram{via} ...")

    try:
        me = await bot.get_me()
    except Exception as exc:
        print(f"\n❌ Не удалось подключиться к Telegram: {exc}")
        if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
            print(
                "\n   Это network-timeout: api.telegram.org недоступен из этой сети.\n"
                "   Решение: впиши в .env рабочий TG_PROXY (http://host:port или socks5://host:port)\n"
                "   или включи VPN на уровне системы и перезапусти скрипт."
            )
        else:
            print("   Проверь, что BOT_TOKEN правильный и скопирован целиком.")
        await bot.session.close()
        return

    # Снимем webhook, если висит — иначе polling не получит сообщения.
    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception as exc:
        print(f"⚠️ Не удалось удалить webhook: {exc}")

    print(
        f"\nБот @{me.username} (id={me.id}) ждёт твоё сообщение.{via}\n"
        f"Напиши ему что угодно — ответит chat_id.\n"
        f"Важно: другой процесс с этим же токеном НЕ должен работать параллельно.\n"
        f"Для выхода — Ctrl+C.\n"
    )
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nГотово.")
