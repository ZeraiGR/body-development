"""Логика программы: перевод дней, недели, стадии, streak.

current_day (1..30) хранится явно в БД. Неделя и стадия выводятся из него
(см. bot/content/program.py). Перевод дня происходит утром, идемпотентно
по last_morning_date — рестарт бота днём не сбивает счётчик.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.content import program


# --------------------------------------------------------------------------- #
# Даты / время (в таймзоне конфига)
# --------------------------------------------------------------------------- #
def tz(timezone: str) -> ZoneInfo:
    return ZoneInfo(timezone)


def now(timezone: str) -> datetime:
    return datetime.now(tz(timezone))


def today_iso(timezone: str) -> str:
    return now(timezone).date().isoformat()


def is_sunday(timezone: str) -> bool:
    """Понедельник=0 ... Воскресенье=6."""
    return now(timezone).weekday() == 6


def date_iso(offset_days: int, timezone: str) -> str:
    """ISO-дата через offset_days от сегодня."""
    return (now(timezone).date() + timedelta(days=offset_days)).isoformat()


# --------------------------------------------------------------------------- #
# Неделя / стадия по дню
# --------------------------------------------------------------------------- #
def week_for_day(day: int) -> int:
    return program.week_for_day(day)


def stage_for_day(day: int) -> tuple[str, str]:
    return program.stage_for_day(day)


# --------------------------------------------------------------------------- #
# Перевод дня (вызывается утром)
# --------------------------------------------------------------------------- #
async def morning_rollover(state: dict, timezone: str) -> dict:
    """Идемпотентный перевод дня. Возвращает поля для обновления (возможно пусто).

    Логика:
      - если paused — ничего не делаем;
      - если утро уже запускалось сегодня (last_morning_date == today) — пропускаем;
      - иначе: если это НЕ первое утро (last_morning_date задан) — переводим день
        (с учётом «задержаться на неделе»), затем отмечаем last_morning_date.
    """
    today = today_iso(timezone)
    if state["paused"]:
        return {}
    if state["last_morning_date"] == today:
        return {}

    updates: dict = {}
    # Переводим день, только если уже было хотя бы одно утро (иначе это старт — день 1).
    if state["last_morning_date"] is not None:
        if state["week_extra_days"] > 0:
            # Задерживаемся на текущей неделе: день не двигаем, сжигаем один «лишний» день.
            updates["week_extra_days"] = state["week_extra_days"] - 1
        elif state["current_day"] < 30:
            updates["current_day"] = state["current_day"] + 1
        # current_day == 30 и лишних дней нет → программа завершена, держим на 30.

    updates["last_morning_date"] = today
    return updates


# --------------------------------------------------------------------------- #
# Streak
# --------------------------------------------------------------------------- #
async def update_streak(state: dict, timezone: str) -> tuple[int, bool]:
    """Зафиксировать, что вечерние метрики сегодня сданы.

    Возвращает (новый streak, is_new_day). Вызывать один раз за вечер.
    """
    today = today_iso(timezone)
    last = state["last_log_date"]
    if last == today:
        # Уже учтено сегодня (повторная отправка) — без изменений.
        return state["streak"], False

    if last is not None:
        yesterday = date_iso(-1, timezone)
        streak = state["streak"] + 1 if last == yesterday else 1
    else:
        streak = 1
    return streak, True


# --------------------------------------------------------------------------- #
# Утилиты для отчётов
# --------------------------------------------------------------------------- #
def sparkline(values: list[int | None]) -> str:
    """Мини-график из значений 1..10 (None → пробел)."""
    blocks = "▁▂▃▄▅▆▇█"
    out = []
    for v in values:
        if v is None:
            out.append("·")
        else:
            idx = max(0, min(len(blocks) - 1, round((v - 1) / 9 * (len(blocks) - 1))))
            out.append(blocks[idx])
    return "".join(out)


def stats(values: list[int]) -> dict:
    if not values:
        return {"avg": None, "min": None, "max": None}
    return {
        "avg": round(sum(values) / len(values), 1),
        "min": min(values),
        "max": max(values),
    }


def pick_random(items: list[str]) -> str:
    return random.choice(items)
