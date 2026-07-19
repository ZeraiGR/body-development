"""Безопасность: бот общается ТОЛЬКО с владельцем и устойчив к промпт-инъекциям.

Два рубежа защиты:

1. Single-user guard (AuthMiddleware).
   Outer-middleware на message и callback_query: любое событие от пользователя
   с id != ALLOWED_CHAT_ID или из не-приватного чата молча отбрасывается.
   Это единственная точка пропуска — все роутеры идут через неё.

2. Устойчивость к промпт-инъекциям (по сути — отсутствие поверхности атаки).
   Бот полностью шаблонный: в нём НЕТ LLM, поэтому текст пользователя
   нигде не интерпретируется как инструкция. Свободный текст игнорируется
   (бот реагирует только на конкретные команды и кнопки). Дополнительно:
     • callback_data парсится строго по ожидаемым шаблонам (regex/int-range);
       неизвестные/кривые колбэки игнорируются;
     • пользовательский текст никогда не подставляется в URL, команды оболочки,
       eval/exec или SQL — только параметризованные запросы (см. db.py);
     • нигде нет eval/exec/os.system/pickle от данных пользователя.

Если позже сюда вернётся LLM (например, для вечернего фидбека) — пользовательский
текст обязан передаваться как *данные*, а не как часть системного промпта,
и модель не должна получать права вызывать инструменты по содержанию сообщения.
"""
from __future__ import annotations

import logging

from aiogram import BaseMiddleware

log = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """Пропускает только владельца (ALLOWED_CHAT_ID) и только личные чаты."""

    def __init__(self, allowed_user_id: int) -> None:
        self.allowed_user_id = allowed_user_id

    async def __call__(self, handler, event, data):  # type: ignore[no-untyped-def]
        user = getattr(event, "from_user", None)

        # Чат: у Message это event.chat, у CallbackQuery — event.message.chat.
        chat = getattr(event, "chat", None)
        if chat is None:
            message = getattr(event, "message", None)
            chat = getattr(message, "chat", None)

        if user is None or user.id != self.allowed_user_id:
            log.warning(
                "Отброшен доступ: user=%s chat=%s (разрешён только %s)",
                getattr(user, "id", None),
                getattr(chat, "id", None),
                self.allowed_user_id,
            )
            return  # не вызываем handler — событие отброшено

        # Запрещаем групповые/канальные чаты даже для владельца.
        if chat is not None and chat.type != "private":
            log.warning("Отброшен не-приватный чат: %s", chat.type)
            return

        return await handler(event, data)
