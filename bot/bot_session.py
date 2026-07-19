"""Сборка aiogram-бота с опциональной поддержкой прокси.

Если Telegram API недоступен напрямую (например, заблокирован в сети),
пропиши в .env переменную TG_PROXY. Поддерживаются:
  - HTTP/HTTPS:  http://host:port   или  http://user:pass@host:port
  - SOCKS5/SOCKS4: socks5://host:port (нужен пакет aiohttp-socks)

Таймаут намеренно увеличен до 30 c — прокси бывают медленными.
"""
from __future__ import annotations

from aiohttp import ClientTimeout
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

_TIMEOUT = ClientTimeout(total=30)


def build_bot(
    token: str,
    *,
    proxy: str | None = None,
    parse_mode: str | None = None,
) -> Bot:
    if not proxy:
        return Bot(token=token, default=DefaultBotProperties(parse_mode=parse_mode))

    low = proxy.lower()
    if low.startswith("socks"):
        try:
            from aiohttp_socks import ProxyConnector
        except ImportError as exc:
            raise RuntimeError(
                "Для SOCKS-прокси установи пакет: pip install aiohttp-socks"
            ) from exc
        session = AiohttpSession(
            connector=ProxyConnector.from_url(proxy), timeout=_TIMEOUT
        )
    else:  # http:// или https://
        session = AiohttpSession(proxy=proxy, timeout=_TIMEOUT)

    return Bot(token=token, session=session, default=DefaultBotProperties(parse_mode=parse_mode))
