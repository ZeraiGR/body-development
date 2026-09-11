"""Шаблоны сообщений и клавиатур (детерминированные, без LLM).

Тон (CLAUDE.md): дружелюбный, системный, без давления, evidence-based.
Чтение, движение и самочувствие учитываются отдельно.
"""
from __future__ import annotations

from datetime import date, timedelta
import math
import re

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.content import program
from bot.content.articles import get_article
from config import config
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


# --------------------------------------------------------------------------- #
# Клавиатуры
# --------------------------------------------------------------------------- #


def ping_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Сделал", callback_data="ping:done")
    kb.button(text="⏩ Пропустить", callback_data="ping:skip")
    kb.adjust(2)
    return kb.as_markup()


def feedback_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🥵 Было тяжело — остаться на неделе", callback_data="hard")
    kb.adjust(1)
    return kb.as_markup()


# --------------------------------------------------------------------------- #
# Тексты: утро / день / вечер
# --------------------------------------------------------------------------- #
def lesson_pages(day: int) -> list[str]:
    """Telegram-sized pages, split only between paragraphs."""
    article = get_article(day) or {}
    body = article.get("body_markdown", article.get("green", ""))
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
    body = re.sub(r"^#{1,4} (.+)$", r"*\1*", body, flags=re.MULTILINE)
    body = body.replace("**", "*")
    pages, current = [], ""
    paragraphs = [p.strip() for p in body.split('\n\n') if p.strip()]
    blocks = []
    pending_heading = ''
    for paragraph in paragraphs:
        if re.fullmatch(r'\*[^*\n]+\*', paragraph):
            pending_heading += paragraph + '\n\n'
            continue
        blocks.append(pending_heading + paragraph)
        pending_heading = ''
    if pending_heading:
        blocks.append(pending_heading.strip())
    for paragraph in blocks:
        if len(current) + len(paragraph) + 2 > 1200:
            if current:
                pages.append(current)
            current = ""
        # Future editorial mistakes must not create an oversized message.
        while len(paragraph) > 1200:
            cut = paragraph.rfind(" ", 0, 1200)
            cut = cut if cut > 0 else 1200
            pages.append(paragraph[:cut])
            paragraph = paragraph[cut:].strip()
        current += ("\n\n" if current else "") + paragraph
    if current:
        pages.append(current)
    return pages or ["Этот урок пока готовится."]


def theory_kb(telegraph_url: str | None, day: int = 1, *, read: bool = False, page: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Продолжить чтение" if page else "📖 Читать здесь", callback_data=f"learn:open:{day}")
    article = get_article(day) or {}
    if article.get('image'):
        kb.button(text="Посмотреть движение", url=article['image']['url'])
    if telegraph_url:
        kb.button(text="Открыть статью с иллюстрацией", url=telegraph_url)
        kb.button(text="✓ Прочитал статью", callback_data=f"learn:done:{day}:{planner.today_iso(config.schedule.timezone)}")
    if read:
        kb.button(text="✓ Прочитано · перечитать", callback_data=f"learn:page:{day}:0")
    kb.button(text="Все темы", callback_data="learn:list:0")
    kb.adjust(1)
    return kb.as_markup()


def theory_text(day: int, telegraph_url: str | None, *, read_at: str | None = None, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    article = get_article(day) or {}
    title = article.get("title", f"День {day}")
    minutes = max(1, math.ceil(len(article.get("body_markdown", "").split()) / 180))
    status = f"\n✓ Уже прочитано {read_at}. Можно вернуться к любому фрагменту." if read_at else ""
    text = (
        f"📖 *День {day} · {title}*\n{minutes} мин чтения{status}\n\n"
        f"{article.get('teaser', article.get('green', ''))}\n\n"
        f"*Попробовать сегодня:* {article.get('action', '')}\n\n"
        "Место чтения сохранится. Можно вернуться к нему позже."
    )
    return text, theory_kb(telegraph_url, day, read=bool(read_at), page=page)


def lesson_page_text(day: int, page: int, telegraph_url: str | None) -> tuple[str, InlineKeyboardMarkup]:
    article = get_article(day) or {}
    pages = lesson_pages(day)
    page = max(0, min(page, len(pages) - 1))
    text = f"📖 *{article.get('title', '')}*\nФрагмент {page + 1} из {len(pages)}\n\n{pages[page]}"
    kb = InlineKeyboardBuilder()
    if page > 0:
        kb.button(text="← Назад", callback_data=f"learn:page:{day}:{page-1}")
    if page < len(pages) - 1:
        kb.button(text="Читать дальше →", callback_data=f"learn:page:{day}:{page+1}")
    else:
        video = article.get("video")
        if video:
            text += f"\n\n🎬 *Посмотреть:* {video['title']}\n{video['author']} · {video['language']}\n{video['why']}"
            kb.button(text="🎬 Видео по теме", url=video["url"])
        text += f"\n\n*Попробуй сейчас:* {article.get('action', '')}"
        kb.button(text="✓ Прочитал", callback_data=f"learn:done:{day}:{planner.today_iso(config.schedule.timezone)}")
    if article.get('image'):
        kb.button(text="Посмотреть движение", url=article['image']['url'])
    if telegraph_url:
        kb.button(text="Статья с иллюстрацией", url=telegraph_url)
    kb.button(text="К теме", callback_data=f"learn:card:{day}")
    kb.adjust(1)
    return text, kb.as_markup()


def morning_text(day: int, telegraph_url: str | None, *, done: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    article = get_article(day) or {}
    today = planner.today_iso(config.schedule.timezone)
    text = (
        f"☀️ *{article.get('title', 'Немного движения')}*\nДень {day} · неделя {program.week_for_day(day)}\n\n"
        f"{article.get('teaser', article.get('green', ''))}\n\n"
        f"*Первый шаг:* {article.get('action', 'Пройдись минуту в удобном темпе.')}\n\n"
        "Урок можно прочитать прямо здесь, по небольшому фрагменту."
    )
    kb = InlineKeyboardBuilder.from_markup(theory_kb(telegraph_url, day))
    if not done:
        kb.button(text="✓ Попробовал движение", callback_data=f"move:{today}:{day}")
    kb.adjust(1)
    return text, kb.as_markup()


def day_ping_text() -> tuple[str, InlineKeyboardMarkup]:
    variants = [
        "🚶 Освободи себе минуту: встань и пройдись в удобном темпе. Можно просто до окна и обратно.",
        "🌿 Закончил небольшое дело? Смени положение, отпусти плечи и сделай несколько шагов.",
        "⏰ Короткая пауза для тела. Отодвинь стул и немного походи. Начать можно с тридцати секунд.",
    ]
    return planner.pick_random(variants), ping_kb()


# --------------------------------------------------------------------------- #
# Ответ после вечерней записи
# --------------------------------------------------------------------------- #
def feedback_text(day: int, pain_level: int | None, location: str | None, streak: int) -> tuple[str, InlineKeyboardMarkup]:
    comments = {
        0: "Сегодня спина не беспокоила. Сохрани удобный темп, без обязательного усложнения.",
        1: "Отметили слабый дискомфорт. Завтра ориентируйся на переносимость знакомых движений.",
        2: "При умеренном дискомфорте можно уменьшить объём или амплитуду. Усиливающую боль нагрузку останови.",
        3: "При сильной боли не продавливай упражнение. Если боль нарастает или мешает обычным делам, обратись к врачу.",
    }
    text = "✓ Вечерняя запись сохранена.\n\n" + comments.get(pain_level, "Спасибо за запись.")
    text += "\n\nЗавтра достаточно начать с одного знакомого движения."
    return text, feedback_kb()


def hard_confirm_text(extra_days: int) -> str:
    return (
        f"Понял, без спешки 🙌 Задержимся на этой неделе ещё на {extra_days} "
        f"{_plural_days(extra_days)}. Тело адаптируется не по графику, а по "
        f"готовности — это нормально. Восстановим ритм спокойно."
    )


def gentle_miss_text() -> str:
    return (
        "Ничего страшного, отдых — тоже часть процесса 🌿 "
        "Завтра можно вернуться к одному знакомому действию."
    )


# --------------------------------------------------------------------------- #
# Воскресный отчёт
# --------------------------------------------------------------------------- #
def weekly_report_text(logs: list[dict], timezone: str, day: int,
                       readings: list[dict] | None = None, end_date: str | None = None) -> str:
    """Calendar report: unknown/legacy scales are never averaged with 0–3."""
    end = date.fromisoformat(end_date) if end_date else planner.now(timezone).date()
    window = [end + timedelta(days=-i) for i in range(6, -1, -1)]
    by_date = {row["date"]: row for row in logs}
    reading_dates = {row["date"] for row in readings or [] if row.get('status', 'done') == 'done'}
    started_dates = {row['date'] for row in readings or [] if row.get('status') == 'partial'} - reading_dates
    lines = [f"📊 *Неделя {window[0]:%d.%m.%Y} — {end:%d.%m.%Y}*",
             "Боль: 0 — нет, 1 — слабая, 2 — умеренная, 3 — сильная.",
             "— означает, что записи нет.\n"]
    pain_series = []
    completed = full = partial = legacy = 0
    for current in window:
        iso = current.isoformat()
        row = by_date.get(iso, {})
        complete = bool(row.get("evening_done"))
        completed += complete
        pain = row.get("pain")
        valid = row.get("pain_scale") == 3 and pain in (0, 1, 2, 3)
        if pain is not None and not valid:
            legacy += 1
        pain_series.append(pain if valid and complete else None)
        pain_label = str(pain) if valid and complete else (f"{pain} (ранняя запись)" if pain is not None and not valid else "—")
        status = row.get("habits_status")
        full += complete and status == "yes"
        partial += complete and status == "partial"
        movement = {"yes": "да", "partial": "немного", "no": "нет"}.get(status, "—")
        if status is None and row.get("habits_done"):
            movement = "отмечено ранее"
        if row.get("morning_done") and status is None:
            movement = "утренний шаг"
        reading = "✓" if iso in reading_dates else ("начато" if iso in started_dates else "—")
        lines.append(f"{current:%d.%m} · боль {pain_label} · движение {movement} · чтение {reading}")
    lines += [f"\nВечерних записей: {completed}/7.",
              f"Движение по вечерним ответам: {full} полных, {partial} частичных.",
              f"Дней с чтением: {len(reading_dates & {d.isoformat() for d in window})}/7."]
    vals = [v for v in pain_series if v is not None]
    if vals:
        lines.append(f"Боль за неделю: {planner.sparkline(pain_series)} · средняя {sum(vals)/len(vals):.1f} из 3.")
    if legacy:
        lines.append("Ранние оценки показаны как записаны: их шкала неизвестна, в среднее они не входят.")
    lines.append("\nВыбери одно действие, которое удобно повторить завтра. Пропуски не отменяют сделанного.")
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
        f"📅 Вечерних отметок подряд: {state['streak']} {_plural_days(state['streak'])}\n"
        f"⏸ Пауза: {paused}{extra_line}\n"
        f"📅 Последняя отметка: {state['last_log_date'] or '—'}"
    )


def welcome_text() -> str:
    return (
        "Привет! Здесь можно постепенно вернуть движение в обычный день.\n\n"
        "Утром — короткая история о теле и одно действие. Урок читается прямо в чате, "
        "после него можно посмотреть видео. Вечером — запись о самочувствии и о том, что получилось.\n\n"
        "/today — начать сегодня · /theory — читать · /lessons — все темы\n"
        "/report — неделя в датах · /report 2026-09-01 — неделя до указанной даты\n"
        "/goto 3 — открыть прошлый урок · /continue 3 — продолжить программу с дня 3\n"
        "/pause и /resume — управление напоминаниями."
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
