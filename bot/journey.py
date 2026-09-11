"""Shared reading and calendar check-ins for Telegram, VK and MAX."""
from __future__ import annotations

import asyncio
import re
import secrets
from datetime import date, timedelta

from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot import db, messages, planner
from bot.content.articles import ARTICLES, get_article
from config import config

_lock = asyncio.Lock()
_STALE = 'Эта кнопка устарела. /today — урок, /evening — сегодняшняя запись.'


def day_argument(raw: str) -> int | None:
    return int(raw) if re.fullmatch(r'[0-9]{1,2}', raw) and 1 <= int(raw) <= 30 else None


async def lesson(raw: str = ''):
    day = day_argument(raw) if raw else (await db.get_state())['current_day']
    if day is None:
        return 'Укажи номер урока от 1 до 30. Например: /theory 3.', None
    status = await db.reading_status(day)
    return messages.theory_text(day, await db.get_telegraph_link(day), read_at=status['read_at'], page=status['page'])


async def continue_from(raw: str) -> str:
    day = day_argument(raw)
    if day is None:
        return 'Укажи: /continue N, где N от 1 до 30.'
    async with _lock:
        await db.continue_program(day, planner.today_iso(config.schedule.timezone))
    return f'Продолжаем программу с дня {day}. /today — открыть. История чтения и записей сохранена.'


async def reset() -> str:
    async with _lock:
        await db.continue_program(1, planner.today_iso(config.schedule.timezone))
        await db.update_state(paused=0)
    return 'Снова день 1. История чтения и вечерних записей сохранена. /today — открыть урок.'


async def report(raw: str = '') -> str:
    tz = config.schedule.timezone
    try:
        if raw and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw, flags=re.ASCII):
            raise ValueError
        end = date.fromisoformat(raw) if raw else planner.now(tz).date()
        if end > planner.now(tz).date():
            raise ValueError
        start = (end - timedelta(days=6)).isoformat()
    except (ValueError, OverflowError):
        return 'Укажи дату не позднее сегодняшней: /report ГГГГ-ММ-ДД. Без даты — последние 7 дней.'
    logs = await db.logs_between(start, end.isoformat())
    readings = await db.readings_between(start, end.isoformat())
    return messages.weekly_report_text(logs, tz, (await db.get_state())['current_day'], readings, end.isoformat())


async def lesson_list(page: int = 0):
    page = max(0, min(page, 5))
    read = await db.read_days()
    kb = InlineKeyboardBuilder()
    listed = ARTICLES[page * 5:(page + 1) * 5]
    for article in listed:
        day = article['day']
        kb.button(text=f"{'✓' if day in read else '○'} {day}. {article['title']}", callback_data=f'learn:card:{day}')
    if page:
        kb.button(text='← Раньше', callback_data=f'learn:list:{page-1}')
    if page < 5:
        kb.button(text='Следующие темы →', callback_data=f'learn:list:{page+1}')
    kb.adjust(1, 1, 1, 1, 1, 2)
    titles = '\n'.join(f"{'✓' if a['day'] in read else '○'} {a['day']}. {a['title']}" for a in listed)
    return (f'📚 *Твои темы* · прочитано {len(read)}/30\n\n{titles}\n\n'
            'Просмотр прошлого урока не меняет день программы.'), kb.as_markup()


async def evening():
    """Resume the same draft across restarts and messengers."""
    async with _lock:
        today = planner.today_iso(config.schedule.timezone)
        draft = await db.get_checkin(today)
        if not draft or not draft['token']:
            day = (await db.get_state())['current_day']
            draft = await db.start_checkin(today, day, secrets.token_hex(4),
                                          completed=bool((await db.get_log(today) or {}).get('evening_done')))
            # Existing completed records stay intact until explicit editing.
            if (await db.get_log(today) or {}).get('evening_done'):
                return await _saved(draft)
        if draft['step'] == 'done':
            return await _saved(draft)
        return _question(draft)


async def _saved(draft):
    log = await db.get_log(draft['date']) or {}
    text, _ = messages.feedback_text(draft['day'], log.get('pain') if log.get('pain_scale') == 3 else None, None, 0)
    text += '\n\nДвижение: ' + {'yes': 'выполнено', 'partial': 'частично', 'no': 'сегодня нет'}.get(log.get('habits_status'), 'отмечено ранее') + '.'
    readings = await db.readings_between(draft['date'], draft['date'])
    done = sorted(r['day'] for r in readings if r['status'] == 'done')
    if done:
        text += '\nПрочитаны уроки: ' + ', '.join(map(str, done)) + '.'
    kb = InlineKeyboardBuilder()
    kb.button(text='Изменить ответы', callback_data=f"check:{draft['date']}:{draft['day']}:{draft['token']}:edit:start")
    kb.button(text='Читать урок', callback_data=f"learn:open:{draft['day']}")
    kb.adjust(1)
    return text, kb.as_markup()


def _question(draft):
    step, day = draft['step'], draft['day']
    if step == 'pain':
        title = (f"🌙 *Как прошёл день?* {date.fromisoformat(draft['date']):%d.%m}\n\n"
                 'Три коротких вопроса: самочувствие, движение, чтение.\n\n*Насколько спина беспокоила сегодня?*')
        choices = [('Не беспокоила', '0'), ('Слабо', '1'), ('Умеренно', '2'), ('Сильно', '3')]
    elif step == 'movement':
        title = '*Удалось подвигаться сегодня?*\nПрогулка, разминка или упражнения — всё считается.'
        choices = [('Да, как планировал', 'yes'), ('Немного', 'partial'), ('Сегодня нет', 'no')]
    else:
        title = f'*Читал сегодня урок {day}?*\nДругую тему можно отметить в /lessons. Уже сохранённое чтение останется в истории.'
        choices = [('Да, дочитал', 'yes'), ('Начал, продолжу позже', 'partial'), ('Пока нет', 'no')]
    kb = InlineKeyboardBuilder()
    for label, value in choices:
        kb.button(text=label, callback_data=f"check:{draft['date']}:{day}:{draft['token']}:{step}:{value}")
    kb.adjust(2 if step == 'pain' else 1)
    return title, kb.as_markup()


async def action(data: str):
    async with _lock:
        try:
            return await _action(data)
        except (ValueError, IndexError):
            return _STALE, None


async def _action(data: str):
    parts = data.split(':')
    today = planner.today_iso(config.schedule.timezone)
    if parts[0] == 'learn':
        kind = parts[1]
        if len(parts) != (4 if kind in ('page', 'done') else 3):
            raise ValueError
        if kind == 'list':
            return await lesson_list(int(parts[2]))
        day = day_argument(parts[2])
        if day is None:
            raise ValueError
        if kind == 'card':
            return await lesson(str(day))
        if kind in ('open', 'page'):
            page = (await db.reading_status(day))['page'] if kind == 'open' else int(parts[3])
            page = max(0, min(page, len(messages.lesson_pages(day)) - 1))
            await db.save_reading_page(day, page, today)
            return messages.lesson_page_text(day, page, await db.get_telegraph_link(day))
        if kind == 'done':
            if parts[3] != today:
                return 'Это отметка за другой день. Открой урок заново, чтобы отметить чтение сегодня.', None
            await db.mark_read(day, today)
            article = get_article(day)
            kb = InlineKeyboardBuilder()
            kb.button(text='✓ Попробовал движение', callback_data=f'move:{today}:{day}')
            if day < 30:
                kb.button(text='Следующая тема →', callback_data=f'learn:card:{day+1}')
            kb.button(text='Все темы', callback_data='learn:list:0')
            kb.adjust(1)
            return (f'✓ Урок {day} прочитан. Отметка сохранена за {today}.\n\n'
                    f"*Теперь попробуй:* {article['action']}"), kb.as_markup()
    if parts[0] == 'move' and len(parts) == 3:
        day = day_argument(parts[2])
        if parts[1] != today or day is None:
            return 'Эта отметка относится к другому дню. /today — открыть сегодняшний шаг.', None
        already = bool((await db.get_log(today) or {}).get('morning_done'))
        await db.upsert_log(today, (await db.get_state())['current_day'], morning_done=True)
        text, kb = await lesson(str(day))
        return ('✓ Движение уже отмечено.' if already else '✓ Движение за сегодня отмечено.') + '\n\n' + text, kb
    if parts[0] == 'check' and len(parts) == 6:
        recorded_date, day, token, step, value = parts[1], day_argument(parts[2]), parts[3], parts[4], parts[5]
        draft = await db.get_checkin(today)
        if recorded_date != today or day is None or not draft or draft['day'] != day or draft['token'] != token:
            return _STALE, None
        if step == 'edit' and value == 'start':
            draft = await db.start_checkin(today, day, secrets.token_hex(4))
            return _question(draft)
        accepted = await db.answer_checkin(today, token, step, value, planner.date_iso(-1, config.schedule.timezone))
        if not accepted:
            return 'Этот ответ уже учтён или опрос был начат заново. /evening — продолжить запись.', None
        draft = await db.get_checkin(today)
        return await _saved(draft) if draft['step'] == 'done' else _question(draft)
    raise ValueError
