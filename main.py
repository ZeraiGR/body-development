"""Точка входа: запуск бота (long-polling).

    python3 main.py

Поднимает БД, бота, диспетчер с AuthMiddleware и планировщик рассылок.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import config
from bot import db
from bot.bot_session import build_bot
from bot.handlers import router
from bot.scheduler import BotScheduler
from bot.security import AuthMiddleware
from bot.vk_bot import VKBot
from bot.max_bot import MaxBot
from bot.bridge import bridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("back_bot")


async def main() -> None:
    await db.init_db(config.db_path)

    bot = build_bot(config.bot_token, proxy=config.proxy, parse_mode=ParseMode.MARKDOWN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # Единственный рубеж допуска: только владелец, только личный чат.
    auth = AuthMiddleware(config.chat_id)
    dp.message.outer_middleware(auth)
    dp.callback_query.outer_middleware(auth)

    scheduler = BotScheduler(bot, config.chat_id)
    scheduler.start()

    # Дополнительные каналы (опционально): VK и MAX. Long Poll каждого —
    # отдельной корутиной в этом же цикле; рассылки дублируются через scheduler.
    vk = vk_task = None
    if config.vk_token and config.vk_user_id:
        try:
            vk = VKBot(config.vk_token, config.vk_user_id)
            await vk.start()
            scheduler.vk = vk
            vk_task = asyncio.create_task(vk.run_polling())
            log.info("VK-бот запущен. owner=%s", config.vk_user_id)
        except Exception:
            log.exception("VK-бот не стартовал")
            if vk is not None:
                await vk.close()
            vk = None
    else:
        log.info("VK выключен (VK_TOKEN/VK_USER_ID не заданы)")

    max_bot = max_task = None
    if config.max_token:
        try:
            max_bot = MaxBot(config.max_token)
            await max_bot.start()
            scheduler.max = max_bot
            max_task = asyncio.create_task(max_bot.run_polling())
            log.info("MAX-бот запущен. owner_chat=%s", max_bot.owner_chat_id)
        except Exception:
            log.exception("MAX-бот не стартовал")
            if max_bot is not None:
                await max_bot.close()
            max_bot = None
    else:
        log.info("MAX выключен (MAX_BOT_TOKEN не задан)")

    # Реестр инстансов для кросс-платформенной синхронизации кнопок.
    bridge.tg = bot
    bridge.tg_chat = config.chat_id
    bridge.vk = vk
    bridge.max = max_bot

    log.info("Бот запущен. Владелец chat_id=%s", config.chat_id)

    # Догнать пропущенные за сегодня рассылки (в фоне, чтобы polling шёл сразу).
    asyncio.create_task(scheduler.catch_up())

    try:
        await dp.start_polling(bot)
    finally:
        if vk_task:
            vk_task.cancel()
        if vk:
            await vk.close()
        if max_task:
            max_task.cancel()
        if max_bot:
            await max_bot.close()
        scheduler.shutdown()
        await db.close_db()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Остановлен.")
