"""Конфигурация из переменных окружения (.env).

Все тайминги — локальное время в TIMEZONE. Бот однопользовательский:
работает только с ALLOWED_CHAT_ID, прочих игнорирует.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _required(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise RuntimeError(f"В .env не задана обязательная переменная {key}")
    return value


def _parse_hhmm(value: str) -> tuple[int, int]:
    hh, mm = value.split(":", 1)
    return int(hh), int(mm)


@dataclass(frozen=True)
class Schedule:
    timezone: str
    morning: tuple[int, int]       # (hour, minute)
    evening: tuple[int, int]
    day_ping_start: tuple[int, int]
    day_ping_end: tuple[int, int]
    vps_remind: tuple[int, int]    # ежедневная проверка напоминания об оплате VPS


@dataclass(frozen=True)
class VPSBilling:
    renewal_day: int   # число месяца списания (например, 6)
    cost: str          # "₽593/мес"
    pay_url: str       # ссылка на оплату
    expiry: str        # "2026-08-06" — для первого напоминания


@dataclass(frozen=True)
class Config:
    bot_token: str
    chat_id: int
    schedule: Schedule
    db_path: str
    telegraph_token: str | None
    proxy: str | None  # TG_PROXY (http/https/socks5) — если Telegram API заблокирован в сети
    vps: VPSBilling
    # LLM
    llm_backend: str           # none|ollama|gemini|openrouter
    ollama_host: str           # http://localhost:11434 (или Tailscale-IP макбука на VPS)
    ollama_model: str          # qwen3:32b
    gemini_api_key: str | None
    openrouter_api_key: str | None
    # VK (второй канал; None — выключен)
    vk_token: str | None
    vk_user_id: int | None
    # MAX (третий канал; None — выключен)
    max_token: str | None


def load_config() -> Config:
    chat_raw = _required("ALLOWED_CHAT_ID")
    try:
        chat_id = int(chat_raw)
    except ValueError as exc:
        raise RuntimeError("ALLOWED_CHAT_ID должен быть числом (твой Telegram id)") from exc

    schedule = Schedule(
        timezone=os.getenv("TIMEZONE", "Europe/Moscow").strip(),
        morning=_parse_hhmm(os.getenv("MORNING_TIME", "08:30")),
        evening=_parse_hhmm(os.getenv("EVENING_TIME", "20:30")),
        day_ping_start=_parse_hhmm(os.getenv("DAY_PING_START", "13:00")),
        day_ping_end=_parse_hhmm(os.getenv("DAY_PING_END", "17:00")),
        vps_remind=_parse_hhmm(os.getenv("VPS_REMIND_TIME", "12:00")),
    )

    telegraph_token = os.getenv("TELEGRAPH_TOKEN", "").strip() or None
    proxy = os.getenv("TG_PROXY", "").strip() or None

    vps = VPSBilling(
        renewal_day=int(os.getenv("VPS_RENEWAL_DAY", "6")),
        cost=os.getenv("VPS_COST", "₽593/мес"),
        pay_url=os.getenv("VPS_PAY_URL", "https://my.aeza.ru/services/602586"),
        expiry=os.getenv("VPS_EXPIRY", "2026-08-06"),
    )

    return Config(
        bot_token=_required("BOT_TOKEN"),
        chat_id=chat_id,
        schedule=schedule,
        db_path=os.getenv("DB_PATH", "data/bot.db").strip(),
        telegraph_token=telegraph_token,
        proxy=proxy,
        vps=vps,
        llm_backend=os.getenv("LLM_BACKEND", "none").strip().lower(),
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434").strip().rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3:32b").strip(),
        gemini_api_key=(os.getenv("GEMINI_API_KEY", "").strip() or None),
        openrouter_api_key=(os.getenv("OPENROUTER_API_KEY", "").strip() or None),
        vk_token=os.getenv("VK_TOKEN", "").strip() or None,
        vk_user_id=(
            int(v) if (v := os.getenv("VK_USER_ID", "").strip()).isdigit() else None
        ),
        max_token=os.getenv("MAX_BOT_TOKEN", "").strip() or None,
    )


# Один объект конфига на весь процесс.
config = load_config()
