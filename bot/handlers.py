"""Хендлеры: команды и колбэки.

Безопасность: AuthMiddleware (см. security.py) уже гарантировал, что событие
пришло от владельца из приватного чата. Поэтому здесь можно считать, что
обращается только хозяин. Пользовательский текст нигде не интерпретируется —
только конкретные команды и строго разобранные callback_data.
"""
from __future__ import annotations

import asyncio
import os

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from config import config
from bot import db, llm, llm_context, messages, planner
from bot.bridge import settle

router = Router()


# --------------------------------------------------------------------------- #
# Утилиты разбора колбэков (строгие)
# --------------------------------------------------------------------------- #
def parse_rating(data: str, prefix: str) -> int | None:
    """'pain:7' -> 7. Неизвестный формат / выход за 1..10 -> None."""
    if not data.startswith(f"{prefix}:"):
        return None
    raw = data.split(":", 1)[1]
    if not raw.isdigit():
        return None
    value = int(raw)
    return value if 1 <= value <= 10 else None


async def _send_weekly(message_or_cb) -> None:
    tz = config.schedule.timezone
    state = await db.get_state()
    logs = await db.logs_between(planner.date_iso(-6, tz), planner.today_iso(tz))
    await message_or_cb.message.answer(  # type: ignore[attr-defined]
        messages.weekly_report_text(logs, tz, state["current_day"])
    )


# --------------------------------------------------------------------------- #
# Команды
# --------------------------------------------------------------------------- #
@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(messages.welcome_text())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Команды:\n"
        "/status — где я сейчас (день/неделя/стрик)\n"
        "/today — показать утреннее сообщение дня вручную\n"
        "/evening — запустить вечерний опрос вручную\n"
        "/ping — дневной микро-пинг вручную\n"
        "/report — недельный отчёт с графиком метрик\n"
        "/chat <текст> — поговорить с ИИ-ассистентом (или просто напиши текст)\n"
        "/remember — обновить память ИИ (сжать историю)\n"
        "/pause — поставить рассылки на паузу\n"
        "/resume — снять паузу\n"
        "/next — перескочить на следующий день (dev)\n"
        "/hard — задержаться на текущей неделе ещё на 2 дня\n"
        "/goto N — перейти на любой день (1–30), если отстал/забежал вперёд\n"
        "/mute — отключить рассылки в этом мессенджере · /unmute — вернуть\n"
        "/reset — начать программу заново с дня 1"
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    state = await db.get_state()
    url = await db.get_telegraph_link(state["current_day"])
    await message.answer(messages.status_text(state, url))


@router.message(Command("report"))
async def cmd_report(message: Message) -> None:
    await _send_weekly(message)


@router.message(Command("pause"))
async def cmd_pause(message: Message) -> None:
    await db.update_state(paused=1)
    await message.answer("⏸ Пауза включена. Рассылки не придут, пока не нажмёшь /resume.")


@router.message(Command("resume"))
async def cmd_resume(message: Message) -> None:
    await db.update_state(paused=0)
    await message.answer("▶️ Снова в строю. Продолжаем 💪")


@router.message(Command("next"))
async def cmd_next(message: Message) -> None:
    state = await db.get_state()
    new_day = min(state["current_day"] + 1, 30)
    await db.update_state(current_day=new_day, last_morning_date=planner.today_iso(config.schedule.timezone))
    await message.answer(f"⏭ Перешёл на день {new_day}.")


@router.message(Command("goto"))
async def cmd_goto(message: Message) -> None:
    """Перейти на любой день: /goto N (1..30). Не двигает стрик/метрики — только курсор дня."""
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.answer("Напиши: /goto N, где N — номер дня (1–30). Например /goto 3.")
        return
    day = max(1, min(30, int(parts[1].strip())))
    await db.update_state(current_day=day)
    state = await db.get_state()
    url = await db.get_telegraph_link(day)
    await message.answer(
        f"📍 Переключился на день {day} · неделя {program.week_for_day(day)}.\n"
        f"Дальше курс продолжается отсюда вперёд. /today — утреннее сообщение этого дня."
        + (f"\n🔗 Теория: {url}" if url else "")
    )


@router.message(Command("hard"))
async def cmd_hard(message: Message) -> None:
    extra = 2
    await db.update_state(week_extra_days=extra)
    await message.answer(messages.hard_confirm_text(extra))


@router.message(Command("reset"))
async def cmd_reset(message: Message) -> None:
    await db.update_state(
        current_day=1,
        week_extra_days=0,
        last_morning_date=None,
        last_log_date=None,
        streak=0,
        paused=0,
    )
    await message.answer("🔄 Сброс. Снова День 1, Неделя 1. Поехали заново 🌱")


@router.message(Command("mute"))
async def cmd_mute(message: Message) -> None:
    await db.set_channel("tg", muted=True)
    await message.answer("🔇 Рассылки в Telegram отключены. Команды работают. /unmute — вернуть.")


@router.message(Command("unmute"))
async def cmd_unmute(message: Message) -> None:
    await db.set_channel("tg", muted=False)
    await message.answer("🔔 Рассылки в Telegram снова включены.")


# --------------------------------------------------------------------------- #
# Фото «до/после» + AI-анализ осанки (minicpm-v)
# --------------------------------------------------------------------------- #
@router.message(F.photo)
async def on_photo(message: Message) -> None:
    """Фото с подписью /before или /after — сохраняем для сравнения осанки."""
    cap = (message.caption or "").strip().lower()
    role = None
    if cap.startswith("/before"):
        role = "before"
    elif cap.startswith("/after"):
        role = "after"
    if role is None:
        await message.answer(
            "📸 Пришли фото с подписью /before или /after — сохраню для анализа осанки. "
            "Когда будет пара до/после — /analyze сравнит через ИИ."
        )
        return
    today = planner.today_iso(config.schedule.timezone)
    os.makedirs("data/photos", exist_ok=True)
    path = f"data/photos/{role}_{today}.jpg"
    try:
        await message.bot.download(message.photo[-1], destination=path)
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"⚠️ Не удалось сохранить фото: {exc}")
        return
    note = message.caption.replace("/before", "").replace("/after", "").strip()
    await db.add_photo(role, path, note)
    await message.answer(
        f"📸 Сохранено: *{role}* ({today}). "
        + ("Когда будет пара до/после — /analyze сравнит осанку." if role == "before"
           else "Теперь /analyze — сравнит «до» и «после» через ИИ.")
    )


@router.message(Command("analyze"))
async def cmd_analyze(message: Message) -> None:
    """Сравнить последние фото до/после через vision-модель."""
    before = await db.latest_photo("before")
    after = await db.latest_photo("after")
    if not (before and after):
        await message.answer("Нужны оба фото: пришли /before + фото и /after + фото, потом /analyze.")
        return
    await message.answer("🔍 Сравниваю фото до/после через ИИ (minicpm-v)… это ~30 сек.")
    prompt = (
        "Сравни две фотографии осанки (первая — «до», вторая — «после») мужчины-разработчика "
        "с гиперлордозом, кифозом и асимметрией (корпус сдвинут влево, правая сторона гипертонична). "
        "Кратко (4-7 предложений): что изменилось в осанке/плечах/пояснице/асимметрии, "
        "что стало лучше, на что обратить внимание. Тёплый, ободряющий тон. На русском."
    )
    reply = await llm.vision_analyze(prompt, [before["path"], after["path"]])
    await message.answer(
        reply or "🤖 ИИ-анализ сейчас недоступен (minicpm-v не отвечает). Попробуй позже."
    )


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    """Показать теорию + утренний запуск текущего дня вручную (не двигает счётчик)."""
    state = await db.get_state()
    day = state["current_day"]
    url = await db.get_telegraph_link(day)
    text, kb = messages.morning_text(day, url)
    await message.answer(text, reply_markup=kb)


@router.message(Command("theory", "day"))
async def cmd_theory(message: Message) -> None:
    """Открыть теорию любого дня: /theory N (алиас /day N). Без аргумента — текущий.
    Счётчик дней НЕ двигает — это просто вызов теории."""
    parts = (message.text or "").split()
    day = None
    if len(parts) >= 2 and parts[1].strip().isdigit():
        d = int(parts[1].strip())
        if 1 <= d <= 30:
            day = d
    if day is None:
        day = (await db.get_state())["current_day"]
    url = await db.get_telegraph_link(day)
    text, kb = messages.theory_text(day, url)
    await message.answer(text, reply_markup=kb)


@router.message(Command("evening"))
async def cmd_evening(message: Message) -> None:
    """Запустить вечерний опрос вручную."""
    state = await db.get_state()
    text, kb = messages.evening_intro_text(state["current_day"])
    await message.answer(text, reply_markup=kb)


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    """Дневной микро-пинг вручную (для проверки/когда пропустили по расписанию)."""
    text, kb = messages.day_ping_text()
    await message.answer(text, reply_markup=kb)


# --------------------------------------------------------------------------- #
# Утро / дневной пинг (кнопки)
# --------------------------------------------------------------------------- #
async def _settle_cb(cb: CallbackQuery, toast: str) -> None:
    """Закрыть inline-кнопку: показать toast и убрать ТОЛЬКО клавиатуру.

    Текст сообщения (теория, ссылки, переписка) НЕ трогается — пользователь
    просил убирать только кнопки, не теряя информацию.
    """
    if toast:
        await cb.answer(toast)
    else:
        await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        # сообщение старее 48ч или клавиатура уже снята — ничего не делаем.
        pass


@router.callback_query(F.data == "morning:done")
async def cb_morning_done(cb: CallbackQuery) -> None:
    today = planner.today_iso(config.schedule.timezone)
    already = bool((await db.get_log(today) or {}).get("morning_done"))
    state = await db.get_state()
    await db.upsert_log(today, state["current_day"], morning_done=True)
    await _settle_cb(cb, "Уже отмечено ✅" if already else "Утренний запуск засчитан 🔥")
    if not already:
        await settle(today, "morning", "tg")


@router.callback_query(F.data == "morning:later")
async def cb_morning_later(cb: CallbackQuery) -> None:
    today = planner.today_iso(config.schedule.timezone)
    await _settle_cb(cb, "Окей, без давления 🌿")
    await settle(today, "morning", "tg")


@router.callback_query(F.data == "ping:done")
async def cb_ping_done(cb: CallbackQuery) -> None:
    today = planner.today_iso(config.schedule.timezone)
    await _settle_cb(cb, "👍 Красава, тело скажет спасибо")
    await settle(today, "ping", "tg")


@router.callback_query(F.data == "ping:skip")
async def cb_ping_skip(cb: CallbackQuery) -> None:
    today = planner.today_iso(config.schedule.timezone)
    await _settle_cb(cb, "Без проблем, в следующий раз 🙂")
    await settle(today, "ping", "tg")


@router.callback_query(F.data == "theory:done")
async def cb_theory_done(cb: CallbackQuery) -> None:
    """«Прочитал» в /theory — убрать кнопку, сообщение оставить."""
    await _settle_cb(cb, "Прочитано 📖")


# --------------------------------------------------------------------------- #
# Вечер: боль -> жёсткость -> привычки -> фидбек
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("pl:"))
async def cb_pain_level(cb: CallbackQuery) -> None:
    """Уровень боли (0..3) → показать выбор локации."""
    raw = cb.data.split(":", 1)[1]
    if not raw.isdigit():
        await cb.answer()
        return
    level = int(raw)
    if not 0 <= level <= 3:
        await cb.answer()
        return
    day = (await db.get_state())["current_day"]
    await db.upsert_log(planner.today_iso(config.schedule.timezone), day, pain=level)
    text, kb = messages.locations_prompt()
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("loc:"))
async def cb_location(cb: CallbackQuery) -> None:
    """Локация боли → показать привычки."""
    loc = cb.data.split(":", 1)[1] if ":" in cb.data else ""
    if loc not in messages._LOCATIONS:
        await cb.answer()
        return
    day = (await db.get_state())["current_day"]
    await db.upsert_log(planner.today_iso(config.schedule.timezone), day, note=loc)
    text, kb = messages.habits_prompt()
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("habits:"))
async def cb_habits(cb: CallbackQuery) -> None:
    code = cb.data.split(":", 1)[1] if ":" in cb.data else ""
    if code not in ("yes", "partial", "no"):
        await cb.answer()
        return
    habits_done = code in ("yes", "partial")

    tz = config.schedule.timezone
    today = planner.today_iso(tz)
    state = await db.get_state()
    day = state["current_day"]

    today_log = await db.get_log(today) or {}
    pain_level = today_log.get("pain")
    location = today_log.get("note")

    await db.upsert_log(today, day, habits_done=habits_done, evening_done=True)

    new_streak, changed = await planner.update_streak(state, tz)
    if changed:
        await db.update_state(streak=new_streak, last_log_date=today)

    if pain_level is None:
        # Пользователь нажал вне порядка — не падаем, просто благодарим.
        await cb.message.edit_text("Засчитал вечер ✅ Завтра снова соберём метрики.")
        await cb.answer()
        return

    text, kb = messages.feedback_text(day, pain_level, location, new_streak)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "hard")
async def cb_hard(cb: CallbackQuery) -> None:
    extra = 2
    await db.update_state(week_extra_days=extra)
    await cb.message.answer(messages.hard_confirm_text(extra))
    await _settle_cb(cb, "Задерживаемся 🌿")


# --------------------------------------------------------------------------- #
# LLM-чат: /chat <текст>, /remember, и свободный текст (всё от владельца)
# --------------------------------------------------------------------------- #
def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_chat_lock = asyncio.Lock()  # сериализует диалог (single-user) — нет гонки в llm_turns


async def _llm_chat(message: Message, user_text: str) -> None:
    """Свободный текст → LLM (с памятью/контекстом). None = fallback на шаблон."""
    async with _chat_lock:
        # Сначала пишем user-ход, чтобы следующее сообщение его уже видело в истории.
        await db.add_turn("user", user_text)
        system, history, user = await llm_context.build_messages(user_text)
        reply = await llm.generate(system, user, history)  # None если backend=none или сбой
        if reply:
            await db.add_turn("assistant", reply)
            # HTML + экранирование: ответ LLM не сломает разметку (там могут быть *_` и т.п.)
            await message.answer(_html_escape(reply), parse_mode=ParseMode.HTML)
        else:
            await message.answer(messages.llm_offline_text())


@router.message(Command("chat"))
async def cmd_chat(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    user_text = args[1].strip() if len(args) > 1 else ""
    if not user_text:
        await message.answer(
            "Напиши так: /chat <твоё сообщение>.\n"
            "Например: /chat спина сегодня снова каменная после долгой катки"
        )
        return
    await _llm_chat(message, user_text)


@router.message(Command("remember"))
async def cmd_remember(message: Message) -> None:
    new = await llm_context.summarize_text()
    if not new:
        await message.answer("Пока нечего запоминать — давай сначала поболтаем через /chat 🙂")
        return
    await db.set_memory(new)
    await message.answer("🧠 Память обновлена:\n\n" + _html_escape(new), parse_mode=ParseMode.HTML)


# --------------------------------------------------------------------------- #
# Всё остальное от владельца — свободный текст идёт в LLM-чат
# (текст НЕ интерпретируется как инструкция — см. анти-инъекцию в llm_context.py)
# --------------------------------------------------------------------------- #
@router.message()
async def fallback(message: Message) -> None:
    text = (message.text or "").strip()
    if not text:
        return
    await _llm_chat(message, text)
