"""Кросс-платформенный мост: реестр инстансов ботов + синхронизация кнопок.

При выполнении действия (утро/пинг) на одной платформе — убираем inline-кнопки
с сообщения этой же рассылки на ДРУГИХ платформах (TG, Max). VK не редактируется
(ограничение cmid у messages.edit), но остаётся идемпотентным: повторный клик —
no-op (действие уже отмечено в daily_logs).
"""
from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest

from bot import db

log = logging.getLogger(__name__)


class Bridge:
    tg: object | None = None       # aiogram Bot
    vk: object | None = None       # VKBot
    max: object | None = None      # MaxBot
    tg_chat: int | None = None     # chat_id владельца в TG


bridge = Bridge()


async def settle(date: str, kind: str, from_platform: str) -> None:
    """Снять inline-кнопки с рассылки (date, kind) на всех платформах, КРОМЕ from_platform.

    TG — edit_message_reply_markup (только клавиатура, текст не трогаем).
    Max — PUT /messages (переотправляем сохранённый текст без вложений-кнопок).
    """
    refs = await db.get_msg_refs(date, kind)
    for r in refs:
        if r["platform"] == from_platform or not r["message_id"]:
            continue
        try:
            if r["platform"] == "tg" and bridge.tg is not None:
                await bridge.tg.edit_message_reply_markup(
                    int(r["chat_id"]), int(r["message_id"]), reply_markup=None
                )
            elif r["platform"] == "max" and bridge.max is not None:
                await bridge.max._edit(r["message_id"], r.get("text") or "✅", None)
        except TelegramBadRequest:
            pass  # сообщение старое (>48ч) или клавиатура уже снята
        except Exception:
            log.exception("settle %s/%s на %s", kind, date, r["platform"])
