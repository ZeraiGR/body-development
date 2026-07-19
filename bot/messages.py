"""Шаблоны сообщений и клавиатур (детерминированные, без LLM).

Тон (CLAUDE.md): дружелюбный, системный, без давления, evidence-based.
Фидбек строится по формуле §5: [Подтверждение усилий] + [Научный факт]
+ [Связь с привычкой].
"""
from __future__ import annotations

from datetime import timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.content import program
from bot.content.articles import get_article
from bot.content.quotes import get_quote
from bot import planner


# --------------------------------------------------------------------------- #
# Утилиты
# --------------------------------------------------------------------------- #
def _bullets(items: list[str]) -> str:
    return "\n".join(f"• {x}" for x in items)


def _plural_days(n: int) -> str:
    """1 день / 2 дня / 5 дней / 11 дней."""
    if 11 <= n % 100 <= 14:
        return "дней"
    last = n % 10
    if last == 1:
        return "день"
    if 2 <= last <= 4:
        return "дня"
    return "дней"


def _ratings_kb(prefix: str, n: int = 10) -> InlineKeyboardMarkup:
    """Клавиатура 1..n для оценки боли/жёсткости."""
    kb = InlineKeyboardBuilder()
    for value in range(1, n + 1):
        kb.button(text=str(value), callback_data=f"{prefix}:{value}")
    kb.adjust(5)  # две строки по 5
    return kb.as_markup()


# --------------------------------------------------------------------------- #
# Клавиатуры
# --------------------------------------------------------------------------- #
def morning_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Сделал", callback_data="morning:done")
    kb.button(text="⏰ Позже", callback_data="morning:later")
    kb.adjust(2)
    return kb.as_markup()


def ping_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Сделал", callback_data="ping:done")
    kb.button(text="⏩ Пропустить", callback_data="ping:skip")
    kb.adjust(2)
    return kb.as_markup()


def pain_kb() -> InlineKeyboardMarkup:
    """4 уровня боли вместо шкалы 1-10 — гораздо легче оценить."""
    levels = [("Нет", 0), ("Слабо", 1), ("Умеренно", 2), ("Сильно", 3)]
    kb = InlineKeyboardBuilder()
    for label, val in levels:
        kb.button(text=label, callback_data=f"pl:{val}")
    kb.adjust(2, 2)
    return kb.as_markup()


_LOCATIONS = ["поясница", "шея", "грудь", "правая", "левая"]


def locations_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for loc in _LOCATIONS:
        kb.button(text=loc.capitalize(), callback_data=f"loc:{loc}")
    kb.adjust(3)
    return kb.as_markup()


def stiffness_kb() -> InlineKeyboardMarkup:
    return _ratings_kb("stiff")


def habits_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Выполнил ритуал", callback_data="habits:yes")
    kb.button(text="😐 Частично", callback_data="habits:partial")
    kb.button(text="😴 Не сегодня", callback_data="habits:no")
    kb.adjust(1)
    return kb.as_markup()


def feedback_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🥵 Было тяжело — остаться на неделе", callback_data="hard")
    kb.adjust(1)
    return kb.as_markup()


# --------------------------------------------------------------------------- #
# Тексты: утро / день / вечер
# --------------------------------------------------------------------------- #
def theory_text(day: int, telegraph_url: str | None) -> str:
    """Полный текст теории дня (тело статьи) — отдельным сообщением, инлайн."""
    article = get_article(day)
    body = "\n\n".join(article["paragraphs"])
    link = f"\n\n🔗 {telegraph_url}" if telegraph_url else ""
    return f"📚 *День {day} · {article['title']}*\n\n{body}{link}"


def morning_text(day: int, telegraph_url: str | None) -> tuple[str, InlineKeyboardMarkup]:
    week = program.week_for_day(day)
    week_data = program.WEEKS[week]
    stage_name, _ = planner.stage_for_day(day)
    article = get_article(day)
    book = get_quote(day)

    book_line = ""
    if book:
        book_line = (
            f"\n📖 *Move Your DNA:* {book['concept']}\n"
            f"_{book['quote']}_ — стр. {book['page']}\n"
        )
    read_line = f"\n📚 *Читать урок целиком:* 🔗 {telegraph_url}\n" if telegraph_url else ""
    green = article.get("green") or ""
    yellow = article.get("yellow")
    green_line = f"🟢 *Обязательно к усвоению:* {green}\n" if green else ""
    yellow_line = f"🟡 _Опционально (углубление):_ {yellow}\n" if yellow else ""

    text = (
        f"☀️ *Доброе утро!* День {day} · Неделя {week}\n"
        f"🧭 Стадия: _{stage_name}_\n\n"
        f"💧 Выпей стакан воды и сделай 3 глубоких вдоха животом "
        f"(рука на животе — он надувается).\n\n"
        f"{green_line}"
        f"{yellow_line}"
        f"{read_line}"
        f"{book_line}\n"
        f"📋 *Утро:*\n{_bullets(week_data['morning'])}\n\n"
        f"Сделал утренний запуск?"
    )
    return text, morning_kb()


def theory_kb(telegraph_url: str | None) -> InlineKeyboardMarkup:
    """Клавиатура /theory: кнопка-ссылка на статью + «Прочитал» (убирается по клику)."""
    kb = InlineKeyboardBuilder()
    if telegraph_url:
        kb.button(text="📖 Открыть статью", url=telegraph_url)
    kb.button(text="✅ Прочитал", callback_data="theory:done")
    return kb.as_markup()


def theory_text(day: int, telegraph_url: str | None) -> tuple[str, InlineKeyboardMarkup]:
    """Напоминание теории дня: заголовок + главный факт + ссылка на Telegraph."""
    article = get_article(day) or {}
    title = article.get("title", f"День {day}")
    green = article.get("green", "")
    read_line = (
        f"\n\n📚 *Читать целиком:* 🔗 {telegraph_url}"
        if telegraph_url
        else "\n\n(статья пока не загружена)"
    )
    text = (
        f"📖 *День {day}* — {title}\n\n"
        f"🟢 {green}"
        f"{read_line}"
    )
    return text, theory_kb(telegraph_url)


def day_ping_text() -> tuple[str, InlineKeyboardMarkup]:
    variants = [
        "🧘 *Перерыв!* Встань на 2 минуты, разомни шею и грудь. "
        "Если совсем не хочется вставать — надень миостимулятор на 15 минут.",
        "⏰ *Микро-пауза.* 30 секунд: встань, потянись руками вверх, "
        "сделай 2 глубоких вдоха. Диск спины скажет спасибо.",
        "🚶 *Время разминки!* Пройдись до окна и обратно, расправь плечи. "
        "Тело запроектировано под движение, а не под статику.",
    ]
    return planner.pick_random(variants), ping_kb()


def evening_intro_text(day: int) -> tuple[str, InlineKeyboardMarkup]:
    week = program.week_for_day(day)
    week_data = program.WEEKS[week]
    stage_name, _ = planner.stage_for_day(day)

    text = (
        f"🌙 *Вечер!* День {day} · Неделя {week}\n"
        f"🧭 Стадия: _{stage_name}_\n\n"
        f"🎮 Включай сериал или Доту — а спину положи на аппликатор "
        f"Кузнецова минут на 15. Так и отдыхаешь, и спина заодно "
        f"размягчается, без отдельных усилий.\n\n"
        f"📋 *Вечерний ритуал:*\n{_bullets(week_data['evening'])}\n\n"
        f"💡 {week_data.get('book_note', '')}\n\n"
        f"💤 *Как спина сегодня?*"
    )
    return text, pain_kb()


def locations_prompt() -> tuple[str, InlineKeyboardMarkup]:
    return "📍 *Где сильнее всего сегодня?* (один главный участок)", locations_kb()


def stiffness_prompt() -> tuple[str, InlineKeyboardMarkup]:
    return "🪨 *Насколько «каменной» ощущается правая сторона?* (1–10, где 10 — камень)", stiffness_kb()


def habits_prompt() -> tuple[str, InlineKeyboardMarkup]:
    return "✅ *Выполнил вечерний ритуал (аппликатор / мячик / мостик)?*", habits_kb()


# --------------------------------------------------------------------------- #
# Вечерний фидбек (формула §5)
# --------------------------------------------------------------------------- #
def feedback_text(
    day: int,
    pain_level: int,
    location: str | None,
    streak: int,
) -> tuple[str, InlineKeyboardMarkup]:
    stage_name, stage_fact = planner.stage_for_day(day)
    week = program.week_for_day(day)

    # 1. Подтверждение усилий
    if streak >= 2:
        effort = f"Красавчик, уже {streak} {_plural_days(streak)} подряд 💪"
    else:
        effort = "Ты молодец, что не бросаешь 💪"

    # Боль — оценка по уровню (0..3)
    lvl_comments = {
        0: "Боли нет сегодня — отличная динамика 📉",
        1: "Боль слабая — держим спокойный темп.",
        2: "Боль умеренная — продолжаем в том же режиме.",
        3: "Боль сильная сегодня. Если тяжело — можно задержаться на неделе (кнопка ниже).",
    }
    pain_line = lvl_comments.get(pain_level, "Спасибо за метрику.")

    where = f"Участок: *{location}*." if location else ""

    # 2. Научный факт об эффекте текущего этапа
    science = f"Сейчас идёт этап «*{stage_name}*»: {stage_fact}."

    # 3. Связь с привычкой (по неделе)
    habit_tips = {
        1: "Завтра во время сериала или Доты полежи на аппликаторе чуть дольше — фасции размягчаются именно от регулярности.",
        2: "Завтра добавь ягодичный мостик по технике — проснувшиеся ягодицы заберут нагрузку у поясницы.",
        3: "Завтра попробуй мячик под правую лопатку на 60 секунд — точечный релиз мягчит «каменную» сторону.",
        4: "Ты на финальной неделе — держи рутину, она уже работает на тебя. Совсем скоро подведём итог месяца.",
    }
    habit = habit_tips[week]

    parts = [effort, pain_line]
    if where:
        parts.append(where)
    parts.append(science)
    parts.append(habit)
    return "\n\n".join(parts), feedback_kb()


def hard_confirm_text(extra_days: int) -> str:
    return (
        f"Понял, без спешки 🙌 Задержимся на этой неделе ещё на {extra_days} "
        f"{_plural_days(extra_days)}. Тело адаптируется не по графику, а по "
        f"готовности — это нормально. Восстановим ритм спокойно."
    )


def gentle_miss_text() -> str:
    return (
        "Ничего страшного, отдых — тоже часть процесса 🌿 "
        "Восстановим стрик завтра?"
    )


# --------------------------------------------------------------------------- #
# Воскресный отчёт
# --------------------------------------------------------------------------- #
def weekly_report_text(
    logs: list[dict],
    timezone: str,
    day: int,
) -> str:
    """logs — записи daily_logs за последние 7 календарных дней (могут быть не все)."""
    from collections import Counter

    by_date = {row["date"]: row for row in logs}

    today = planner.now(timezone).date()
    window = [(today + timedelta(days=-i)) for i in range(6, -1, -1)]
    iso_window = [d.isoformat() for d in window]
    pain_series = [by_date.get(d, {}).get("pain") for d in iso_window]
    pain_vals = [v for v in pain_series if v is not None]
    ps = planner.stats(pain_vals)
    done = len(pain_vals)

    locs = Counter(
        by_date[d].get("note") for d in iso_window
        if by_date.get(d) and by_date[d].get("note")
    )

    lines = [
        f"📊 *Отчёт за неделю* (день {day})",
        f"Метрик сдано: {done}/7\n",
        f"*Боль (0 — нет · 3 — сильно):* {planner.sparkline(pain_series)}",
    ]
    if ps["avg"] is not None:
        lines.append(f"средний уровень {ps['avg']:.1f} · минимум {ps['min']} · максимум {ps['max']}")
    if locs:
        lines.append("\n*Где болело чаще:* " + ", ".join(f"{l} ×{c}" for l, c in locs.most_common()))

    if done == 0:
        lines.append("\nНа этой неделе метрик пока не было — начнём свежую неделю вместе? 🌱")
    elif ps["avg"] is not None and ps["avg"] <= 1:
        lines.append("\nБоль держится на низком уровне — отличный тренд, так держать! 📉")
    else:
        lines.append("\nТы собираешь данные и не бросаешь — это и есть главное. Двигаемся дальше 💪")

    if day >= 30:
        lines.append(
            "\n🎯 *Ты прошёл месяц!* Фундамент Фазы 1 готов. Дальше — Фаза 2: "
            "коррекция асимметрии и осанка. Готов?"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Прочее
# --------------------------------------------------------------------------- #
def status_text(state: dict, telegraph_url: str | None) -> str:
    day = state["current_day"]
    week = program.week_for_day(day)
    stage_name, _ = planner.stage_for_day(day)
    paused = "⏸ да" if state["paused"] else "нет"
    extra = state["week_extra_days"]
    extra_line = f"\n⏳ Задержка на неделе: ещё {extra} {_plural_days(extra)}" if extra else ""
    return (
        f"📍 *Статус*\n"
        f"День: {day}/30 · Неделя: {week}/4\n"
        f"Стадия: _{stage_name}_\n"
        f"🔥 Стрик: {state['streak']} {_plural_days(state['streak'])}\n"
        f"⏸ Пауза: {paused}{extra_line}\n"
        f"📅 Последняя отметка: {state['last_log_date'] or '—'}"
    )


def welcome_text() -> str:
    return (
        "👋 Привет! Я твой ассистент по реабилитации спины.\n\n"
        "Каждое утро буду приносить порцию теории и утренний запуск, днём — "
        "напоминать про микро-паузы, а вечером — собирать метрики (боль и "
        "жёсткость правой стороны) и поддерживать мотивацию на базе науки.\n\n"
        "Без давления: пропустил день — не страшно, восстановим.\n\n"
        "Команды: /status — где я сейчас · /report — недельный отчёт · "
        "/chat <текст> — поговорить с ИИ · /pause /resume · /reset — начать заново."
    )


def vps_reminder_text(cost: str, pay_url: str, expiry: str, days_left: int) -> str:
    when = "сегодня" if days_left == 0 else f"через {days_left} {_plural_days(days_left)}"
    return (
        f"💳 Не забудь продлить VPS — на нём крутятся бот и VPN.\n"
        f"Тариф {cost}. Списание {expiry} ({when}).\n"
        f"Оплатить: {pay_url}"
    )


def llm_offline_text() -> str:
    return (
        "🤖 ИИ-режим сейчас не на связи (Ollama не отвечает) — отвечу по шаблону, "
        "как обычно. Чтобы включить ИИ: поставь Ollama (ollama serve и "
        "ollama pull qwen3:32b) и в .env задай LLM BACKEND = ollama. "
        "Подробности — в документе про LLM в папке docs."
    )
