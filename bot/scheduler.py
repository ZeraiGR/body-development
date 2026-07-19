"""APScheduler: утренняя/дневная/вечерняя рассылки + самовосстановление.

Устойчивость к провалам связи и перезапускам:
  - _send() ретраит отправку с backoff — переживает кратковременные обрывы
    связи через sing-box (ServerDisconnected/timeout).
  - Каждая рассылка идемпотентна (sent_log за сегодня) и защищена локом —
    cron и sweep не задваивают.
  - catch_up() при старте досылает пропущенное за сегодня по окнам.
  - sweep() раз в 15 мин повторяет ту же логику — если рассылка не дошла
    (сеть отвалилась в момент cron), она уйдёт со следующим sweep'ом.
"""
from __future__ import annotations

import asyncio
import logging
import random

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import config
from bot import db, messages, planner

log = logging.getLogger(__name__)


class BotScheduler:
    def __init__(self, bot: Bot, chat_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.vk = None  # VKBot | None — устанавливается из main.py (если VK настроен)
        self.max = None  # MaxBot | None — устанавливается из main.py (если MAX настроен)
        self._sched = AsyncIOScheduler(timezone=config.schedule.timezone)
        self._lock = asyncio.Lock()  # сериализует проверки sent_log + отправку

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        sch = config.schedule
        self._sched.add_job(
            self._send_morning,
            CronTrigger(hour=sch.morning[0], minute=sch.morning[1], timezone=sch.timezone),
            id="morning", misfire_grace_time=3600, replace_existing=True,
        )
        self._sched.add_job(
            self._day_ping_job,
            CronTrigger(
                hour=sch.day_ping_start[0], minute=sch.day_ping_start[1], timezone=sch.timezone
            ),
            id="day_ping", misfire_grace_time=3600, replace_existing=True,
        )
        self._sched.add_job(
            self._send_evening,
            CronTrigger(hour=sch.evening[0], minute=sch.evening[1], timezone=sch.timezone),
            id="evening", misfire_grace_time=3600, replace_existing=True,
        )
        self._sched.add_job(
            self._maybe_vps_reminder,
            CronTrigger(hour=sch.vps_remind[0], minute=sch.vps_remind[1], timezone=sch.timezone),
            id="vps_remind", misfire_grace_time=3600, replace_existing=True,
        )
        # Самовосстановление: проверяем провалы каждые 15 мин (идемпотентно).
        self._sched.add_job(
            self._sweep, IntervalTrigger(minutes=15, timezone=sch.timezone),
            id="sweep", max_instances=1, coalesce=True, replace_existing=True,
        )
        self._sched.start()
        log.info(
            "Планировщик запущен: утро %02d:%02d, пинг окно %02d:%02d–%02d:%02d, "
            "вечер %02d:%02d, sweep каждые 15 мин (%s)",
            sch.morning[0], sch.morning[1],
            sch.day_ping_start[0], sch.day_ping_start[1], sch.day_ping_end[0], sch.day_ping_end[1],
            sch.evening[0], sch.evening[1], sch.timezone,
        )

    def shutdown(self) -> None:
        self._sched.shutdown(wait=False)

    # ------------------------------------------------------------------ #
    async def _send(self, text: str, reply_markup=None) -> dict:
        """Рассылка в TG (retry/backoff) + дублирование в VK/MAX (best-effort).

        Возвращает {platform: message_id} — id нужны для msg_refs (синхронизация
        кнопок между платформами). mark_sent ставит вызывающий после возврата.
        """
        ids: dict[str, int | str | None] = {}
        if not await db.is_muted("tg"):
            ids["tg"] = await self._send_tg(text, reply_markup)  # поднимет исключение при сбое
        if self.vk is not None and not await db.is_muted("vk"):
            try:
                ids["vk"] = await self.vk.send(text, reply_markup)
            except Exception:
                log.exception("VK: не доставлено (не критично)")
        if self.max is not None and not await db.is_muted("max"):
            try:
                ids["max"] = await self.max.send(text, reply_markup)
            except Exception:
                log.exception("MAX: не доставлено (не критично)")
        return ids

    async def _save_refs(self, date: str, kind: str, ids: dict, text: str) -> None:
        """Запомнить id рассылки по платформам (для снятия кнопок с других)."""
        if ids.get("tg"):
            await db.set_msg_ref(date, kind, "tg", str(self.chat_id), str(ids["tg"]), text)
        if ids.get("vk") and self.vk is not None:
            await db.set_msg_ref(date, kind, "vk", str(self.vk.owner), str(ids["vk"]), text)
        if ids.get("max") and self.max is not None and self.max.owner_chat_id:
            await db.set_msg_ref(date, kind, "max", str(self.max.owner_chat_id), str(ids["max"]), text)

    async def _send_tg(self, text: str, reply_markup=None) -> int | None:
        """TG-отправка с повтором/backoff — переживает провалы связи. Возвращает message_id."""
        last_exc: Exception | None = None
        for attempt in range(4):  # 4 попытки
            try:
                msg = await self.bot.send_message(self.chat_id, text, reply_markup=reply_markup)
                return msg.message_id
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after or 5)
                last_exc = exc
            except (TelegramNetworkError, TelegramServerError) as exc:
                last_exc = exc
                await asyncio.sleep(min(2 ** attempt, 15))  # 1, 2, 4, 8
        log.error("TG: не доставлено после повторов: %s", last_exc)
        raise last_exc  # mark_sent не встанет → catch-up/sweep повторит позже

    def _today(self) -> str:
        return planner.today_iso(config.schedule.timezone)

    # ---------------------------- рассылки ---------------------------- #
    async def _send_morning(self) -> None:
        """Утро: перевод дня (idempotent) + теория + запуск. Идемпотентно."""
        async with self._lock:
            today = self._today()
            state = await db.get_state()
            if state["paused"]:
                return  # пауза — ни перевода дня, ни сообщения
            updates = await planner.morning_rollover(state, config.schedule.timezone)
            if updates:
                await db.update_state(**updates)
                state.update(updates)
            if await db.was_sent(today, "morning"):
                return

            day = state["current_day"]
            url = await db.get_telegraph_link(day)
            text, kb = messages.morning_text(day, url)
            ids = await self._send(text, kb)
            await self._save_refs(today, "morning", ids, text)
            await db.mark_sent(today, "morning")
            log.info("Отправлено утро за %s (день %d)", today, day)
            if planner.is_sunday(config.schedule.timezone):
                await self._send_weekly(day)

    async def _send_weekly(self, day: int) -> None:
        """Воскресный отчёт. Вызывается из _send_morning (уже под локом)."""
        today = self._today()
        if await db.was_sent(today, "weekly"):
            return
        tz = config.schedule.timezone
        logs = await db.logs_between(planner.date_iso(-6, tz), today)
        await self._send(messages.weekly_report_text(logs, tz, day))
        await db.mark_sent(today, "weekly")

    async def _send_ping(self) -> None:
        async with self._lock:
            today = self._today()
            if await db.was_sent(today, "ping"):
                return
            state = await db.get_state()
            if state["paused"]:
                return
            text, kb = messages.day_ping_text()
            ids = await self._send(text, kb)
            await self._save_refs(today, "ping", ids, text)
            await db.mark_sent(today, "ping")
            log.info("Отправлен пинг за %s", today)

    async def _day_ping_job(self) -> None:
        """Cron: в окно пинга засыпает на случайный срок и шлёт пинг."""
        sch = config.schedule
        window_minutes = max(
            0,
            (sch.day_ping_end[0] * 60 + sch.day_ping_end[1])
            - (sch.day_ping_start[0] * 60 + sch.day_ping_start[1]),
        )
        if window_minutes:
            await asyncio.sleep(random.randint(0, window_minutes * 60))
        await self._send_ping()

    async def _send_evening(self) -> None:
        async with self._lock:
            today = self._today()
            if await db.was_sent(today, "evening"):
                return
            state = await db.get_state()
            if state["paused"]:
                return
            text, kb = messages.evening_intro_text(state["current_day"])
            await self._send(text, kb)
            await db.mark_sent(today, "evening")
            log.info("Отправлен вечер за %s", today)

    # -------------------- catch-up + sweep (одно тело) ---------------- #
    async def _apply_windows(self) -> None:
        """Дослать пропущенное за сегодня по временным окнам (идемпотентно).

        morning: [morning, ping_end)   — теорию догоняем, пока ещё «день»
        ping:    [ping_start, evening) — пинг имеет смысл до вечера
        evening: [evening, ∞)          — вечер догоняем в любой момент
        """
        sch = config.schedule
        now = planner.now(sch.timezone)
        cur = now.hour * 60 + now.minute
        m = sch.morning[0] * 60 + sch.morning[1]
        ps = sch.day_ping_start[0] * 60 + sch.day_ping_start[1]
        pe = sch.day_ping_end[0] * 60 + sch.day_ping_end[1]
        ev = sch.evening[0] * 60 + sch.evening[1]

        if m <= cur < pe:
            await self._send_morning()
        if ps <= cur < ev:
            await self._send_ping()
        if cur >= ev:
            await self._send_evening()

    async def _maybe_vps_reminder(self) -> None:
        """Напоминание об оплате VPS за 3 дня до и в день списания (идемпотентно)."""
        async with self._lock:
            today = self._today()
            if await db.was_sent(today, "vps_pay"):
                return
            vps = config.vps
            dom = planner.now(config.schedule.timezone).day
            window = [vps.renewal_day - 3, vps.renewal_day - 2, vps.renewal_day - 1, vps.renewal_day]
            if dom not in window:
                return
            days_left = vps.renewal_day - dom
            await self._send(messages.vps_reminder_text(vps.cost, vps.pay_url, vps.expiry, days_left))
            await db.mark_sent(today, "vps_pay")
            log.info("Отправлено напоминание об оплате VPS за %s", today)

    async def _sweep(self) -> None:
        """Периодическая проверка (каждые 15 мин): дослать проваленное + VPS-напоминание."""
        try:
            await self._apply_windows()
            await self._maybe_vps_reminder()
        except Exception:
            log.exception("sweep: ошибка (не критично, cron продолжит)")

    async def catch_up(self) -> None:
        """При старте — дослать пропущенное (с небольшой паузой на пуск бота)."""
        await asyncio.sleep(3)
        await self._sweep()
