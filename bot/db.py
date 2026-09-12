"""Слой хранилища: SQLite (aiosqlite).

Схема заточена под однопользовательского бота — состояние хранится
в единственной строке user_state (id=1).

Таблицы:
  user_state       — current_day (1..30), streak, paused, week_extra_days,
                     last_log_date, started_at.
  daily_logs       — по строке на календарный день: pain (0..3 с pain_scale), ранние pain/stiffness,
                     флаги утро/вечер/привычки, заметка.
  telegraph_links  — day -> url статьи теории.
"""
from __future__ import annotations

import asyncio
from functools import wraps
from typing import Any, Iterable

import aiosqlite

_db: aiosqlite.Connection | None = None
_write_lock = asyncio.Lock()


def _writer(fn):
    """Prevent another coroutine from committing a partly written check-in."""
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        async with _write_lock:
            try:
                return await fn(*args, **kwargs)
            except BaseException:
                await _conn().rollback()
                raise
    return wrapped


async def init_db(db_path: str) -> None:
    """Открыть соединение и создать схему, если её ещё нет."""
    global _db
    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_state (
            id              INTEGER PRIMARY KEY CHECK (id = 1),
            current_day     INTEGER NOT NULL DEFAULT 1,
            streak          INTEGER NOT NULL DEFAULT 0,
            paused          INTEGER NOT NULL DEFAULT 0,
            week_extra_days INTEGER NOT NULL DEFAULT 0,
            last_morning_date TEXT,                    -- дата последней утренней рассылки (idempotency)
            last_log_date   TEXT,
            started_at      TEXT NOT NULL DEFAULT (date('now'))
        );

        CREATE TABLE IF NOT EXISTS daily_logs (
            date          TEXT PRIMARY KEY,           -- YYYY-MM-DD
            day_number    INTEGER NOT NULL,
            pain          INTEGER,                    -- шкала определяется pain_scale; ранняя неизвестна
            stiffness     INTEGER,                    -- 1..10
            morning_done  INTEGER NOT NULL DEFAULT 0, -- 0/1
            evening_done  INTEGER NOT NULL DEFAULT 0,
            habits_done   INTEGER NOT NULL DEFAULT 0,
            note          TEXT
        );

        CREATE TABLE IF NOT EXISTS telegraph_links (
            day   INTEGER PRIMARY KEY,               -- 1..30
            url   TEXT NOT NULL,
            title TEXT NOT NULL
        );

        -- Что бот уже отправил за календарный день (идемпотентность + catch-up).
        -- kind ∈ {'morning','ping','evening','vps_pay','weekly'}.
        CREATE TABLE IF NOT EXISTS sent_log (
            date TEXT NOT NULL,
            kind TEXT NOT NULL,
            PRIMARY KEY (date, kind)
        );

        -- Память LLM: rolling summary прогресса + последние реплики диалога.
        CREATE TABLE IF NOT EXISTS llm_memory (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            summary     TEXT,
            updated_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS llm_turns (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            role     TEXT NOT NULL,   -- 'user' | 'assistant'
            content  TEXT NOT NULL,
            ts       TEXT NOT NULL
        );

        -- Настройки каналов (платформ): mute-флаг + chat_id владельца.
        -- platform ∈ {'tg','vk','max'}. muted=1 → scheduler не шлёт рассылки сюда.
        CREATE TABLE IF NOT EXISTS channel_settings (
            platform TEXT PRIMARY KEY,
            muted    INTEGER NOT NULL DEFAULT 0,
            chat_id  TEXT
        );

        -- Ссылки на рассылочные сообщения по платформам (синхронизация кнопок):
        -- при выполнении действия на одной платформе — убрать кнопку с других.
        CREATE TABLE IF NOT EXISTS msg_refs (
            date       TEXT NOT NULL,
            kind       TEXT NOT NULL,   -- 'morning' | 'ping'
            platform   TEXT NOT NULL,   -- 'tg' | 'vk' | 'max'
            chat_id    TEXT NOT NULL,
            message_id TEXT NOT NULL,
            text       TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (date, kind, platform)
        );

        -- Фото «до/после» для AI-анализа осанки.
        CREATE TABLE IF NOT EXISTS photos (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            ts   TEXT NOT NULL,
            role TEXT NOT NULL,   -- 'before' | 'after'
            path TEXT NOT NULL,
            note TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_logs_date ON daily_logs(date);

        CREATE TABLE IF NOT EXISTS reading_progress (
            day INTEGER PRIMARY KEY CHECK (day BETWEEN 1 AND 30),
            page INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS reading_events (
            date TEXT NOT NULL,
            day INTEGER NOT NULL CHECK (day BETWEEN 1 AND 30),
            status TEXT NOT NULL DEFAULT 'done',
            PRIMARY KEY (date, day)
        );
        CREATE TABLE IF NOT EXISTS checkin_drafts (
            date TEXT PRIMARY KEY,
            day INTEGER NOT NULL,
            step TEXT NOT NULL DEFAULT 'pain',
            pain INTEGER,
            movement TEXT,
            token TEXT
        );
        """
    )
    # Additive migration: keep all existing dates, readings and measurements.
    columns = {r[1] for r in await (await _db.execute("PRAGMA table_info(daily_logs)")).fetchall()}
    for name, definition in (("habits_status", "TEXT"), ("pain_scale", "INTEGER"), ("ping_done", "INTEGER NOT NULL DEFAULT 0")):
        if name not in columns:
            await _db.execute(f"ALTER TABLE daily_logs ADD COLUMN {name} {definition}")
    for table, additions in (
        ("user_state", (("day_started_date", "TEXT"),)),
        ("reading_events", (("status", "TEXT NOT NULL DEFAULT 'done'"),)),
        ("checkin_drafts", (("movement", "TEXT"), ("token", "TEXT"))),
        ("telegraph_links", (("content_hash", "TEXT"),)),
    ):
        columns = {r[1] for r in await (await _db.execute(f"PRAGMA table_info({table})")).fetchall()}
        for name, definition in additions:
            if name not in columns:
                await _db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    await _db.execute(
        "INSERT OR IGNORE INTO user_state (id, current_day) VALUES (1, 1)"
    )
    await _db.commit()


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


def _conn() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("База не инициализирована — вызови init_db() в startup")
    return _db


# --------------------------------------------------------------------------- #
# user_state
# --------------------------------------------------------------------------- #
async def get_state() -> dict[str, Any]:
    cur = await _conn().execute("SELECT * FROM user_state WHERE id = 1")
    row = await cur.fetchone()
    assert row is not None, "user_state должна быть создана в init_db"
    return dict(row)


@_writer
async def update_state(**fields: Any) -> None:
    if not fields:
        return
    columns = ", ".join(f"{k} = ?" for k in fields)
    await _conn().execute(
        f"UPDATE user_state SET {columns} WHERE id = 1",
        tuple(fields.values()),
    )
    await _conn().commit()


# --------------------------------------------------------------------------- #
# daily_logs
# --------------------------------------------------------------------------- #
async def get_log(date: str) -> dict[str, Any] | None:
    cur = await _conn().execute("SELECT * FROM daily_logs WHERE date = ?", (date,))
    row = await cur.fetchone()
    return dict(row) if row else None


@_writer
async def upsert_log(
    date: str,
    day_number: int,
    *,
    pain: int | None = None,
    stiffness: int | None = None,
    morning_done: bool | None = None,
    evening_done: bool | None = None,
    habits_done: bool | None = None,
    note: str | None = None,
    habits_status: str | None = None,
    ping_done: bool | None = None,
    pain_scale: int | None = None,
) -> None:
    """Создать запись дня (если нет) и обновить только переданные поля."""
    await _conn().execute(
        """
        INSERT INTO daily_logs (date, day_number) VALUES (?, ?)
        ON CONFLICT(date) DO NOTHING
        """,
        (date, day_number),
    )
    updates: dict[str, Any] = {}
    if pain is not None:
        updates["pain"] = pain
    if stiffness is not None:
        updates["stiffness"] = stiffness
    if morning_done is not None:
        updates["morning_done"] = int(morning_done)
    if evening_done is not None:
        updates["evening_done"] = int(evening_done)
    if habits_done is not None:
        updates["habits_done"] = int(habits_done)
    if note is not None:
        updates["note"] = note
    if ping_done is not None:
        updates["ping_done"] = int(ping_done)
    if habits_status is not None:
        updates["habits_status"] = habits_status
    if pain_scale is not None:
        updates["pain_scale"] = pain_scale
    if updates:
        columns = ", ".join(f"{k} = ?" for k in updates)
        await _conn().execute(
            f"UPDATE daily_logs SET {columns} WHERE date = ?",
            (*updates.values(), date),
        )
    await _conn().commit()


async def reading_status(day: int) -> dict:
    cur = await _conn().execute("SELECT page FROM reading_progress WHERE day = ?", (day,))
    row = await cur.fetchone()
    cur = await _conn().execute("SELECT MAX(date) FROM reading_events WHERE day = ? AND status='done'", (day,))
    return {"page": row[0] if row else 0, "read_at": (await cur.fetchone())[0]}


@_writer
async def save_reading_page(day: int, page: int, date: str) -> None:
    await _conn().execute(
        "INSERT INTO reading_progress(day, page) VALUES (?, ?) "
        "ON CONFLICT(day) DO UPDATE SET page=excluded.page", (day, page)
    )
    await _conn().execute("INSERT OR IGNORE INTO reading_events(date, day, status) VALUES (?, ?, 'partial')", (date, day))
    await _conn().commit()


@_writer
async def mark_read(day: int, date: str) -> None:
    await _conn().execute("INSERT INTO reading_events(date, day, status) VALUES (?, ?, 'done') "
                          "ON CONFLICT(date, day) DO UPDATE SET status='done'", (date, day))
    await _conn().commit()


async def readings_between(start: str, end: str) -> list[dict]:
    cur = await _conn().execute(
        "SELECT date, day, status FROM reading_events WHERE date BETWEEN ? AND ? ORDER BY date, day", (start, end)
    )
    return [dict(row) for row in await cur.fetchall()]


async def read_days() -> set[int]:
    cur = await _conn().execute("SELECT DISTINCT day FROM reading_events WHERE status='done'")
    return {row[0] for row in await cur.fetchall()}


async def get_checkin(date: str) -> dict | None:
    cur = await _conn().execute("SELECT * FROM checkin_drafts WHERE date=?", (date,))
    row = await cur.fetchone()
    return dict(row) if row else None


@_writer
async def start_checkin(date: str, day: int, token: str, *, completed: bool = False) -> dict:
    await _conn().execute(
        "INSERT INTO checkin_drafts(date, day, token, step) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(date) DO UPDATE SET day=excluded.day, token=excluded.token, "
        "step=excluded.step, pain=NULL, movement=NULL", (date, day, token, 'done' if completed else 'pain')
    )
    await _conn().commit()
    return await get_checkin(date)


@_writer
async def answer_checkin(date: str, token: str, step: str, value: str, yesterday: str) -> bool:
    """Persist a draft, or atomically finish log + reading + streak + draft."""
    conn = _conn()
    draft = await get_checkin(date)
    if not draft or draft['token'] != token or draft['step'] != step:
        return False
    if step == 'pain' and value in ('0', '1', '2', '3'):
        await conn.execute("UPDATE checkin_drafts SET pain=?, step='movement' WHERE date=?", (int(value), date))
    elif step == 'movement' and value in ('yes', 'partial', 'no'):
        await conn.execute("UPDATE checkin_drafts SET movement=?, step='reading' WHERE date=?", (value, date))
    elif step == 'reading' and value in ('yes', 'partial', 'no'):
        await conn.execute(
            "INSERT INTO daily_logs(date, day_number, pain, pain_scale, habits_done, habits_status, evening_done) "
            "VALUES (?, ?, ?, 3, ?, ?, 1) ON CONFLICT(date) DO UPDATE SET "
            "day_number=excluded.day_number, pain=excluded.pain, pain_scale=3, "
            "habits_done=excluded.habits_done, habits_status=excluded.habits_status, evening_done=1",
            (date, draft['day'], draft['pain'], int(draft['movement'] == 'yes'), draft['movement']),
        )
        if value == 'yes':
            await conn.execute("INSERT INTO reading_events(date, day, status) VALUES (?, ?, 'done') "
                               "ON CONFLICT(date, day) DO UPDATE SET status='done'", (date, draft['day']))
        elif value == 'partial':
            await conn.execute("INSERT OR IGNORE INTO reading_events(date, day, status) VALUES (?, ?, 'partial')",
                               (date, draft['day']))
        state = await get_state()
        if state['last_log_date'] != date:
            streak = state['streak'] + 1 if state['last_log_date'] == yesterday else 1
            await conn.execute("UPDATE user_state SET streak=?, last_log_date=? WHERE id=1", (streak, date))
        await conn.execute("UPDATE checkin_drafts SET step='done' WHERE date=?", (date,))
    else:
        return False
    await conn.commit()
    return True


@_writer
async def continue_program(day: int, today: str) -> None:
    await _conn().execute("UPDATE user_state SET current_day=?, week_extra_days=0, last_morning_date=?, day_started_date=? WHERE id=1", (day, today, today))
    await _conn().execute("DELETE FROM checkin_drafts WHERE date=?", (today,))
    await _conn().commit()


async def logs_between(date_from: str, date_to: str) -> list[dict[str, Any]]:
    cur = await _conn().execute(
        """
        SELECT * FROM daily_logs
        WHERE date BETWEEN ? AND ?
        ORDER BY date ASC
        """,
        (date_from, date_to),
    )
    return [dict(r) for r in await cur.fetchall()]


async def last_n_logs(n: int) -> list[dict[str, Any]]:
    cur = await _conn().execute(
        "SELECT * FROM daily_logs ORDER BY date DESC LIMIT ?", (n,)
    )
    rows = [dict(r) for r in await cur.fetchall()]
    rows.reverse()
    return rows


# --------------------------------------------------------------------------- #
# telegraph_links
# --------------------------------------------------------------------------- #
async def get_telegraph_link(day: int) -> str | None:
    from bot.content.articles import article_digest, get_article
    cur = await _conn().execute(
        "SELECT url, content_hash FROM telegraph_links WHERE day = ?", (day,)
    )
    row = await cur.fetchone()
    article = get_article(day)
    if row and article and article.get('revision') == 2 and row['content_hash'] != article_digest(article):
        return None
    return row["url"] if row else None


@_writer
async def set_telegraph_links(links: Iterable[tuple[int, str, str]]) -> None:
    """Обновить только переданные дни, сохранив хеш опубликованного содержимого."""
    from bot.content.articles import article_digest, get_article
    await _conn().executemany(
        "INSERT OR REPLACE INTO telegraph_links (day, url, title, content_hash) VALUES (?, ?, ?, ?)",
        [(day, url, title, article_digest(get_article(day) or {})) for day, url, title in links],
    )
    await _conn().commit()


# --------------------------------------------------------------------------- #
# sent_log — идемпотентность рассылок и catch-up при старте
# --------------------------------------------------------------------------- #
@_writer
async def mark_sent(date: str, kind: str) -> None:
    """Отметить, что рассылка kind за дату date отправлена."""
    await _conn().execute(
        "INSERT OR REPLACE INTO sent_log (date, kind) VALUES (?, ?)", (date, kind)
    )
    await _conn().commit()


async def was_sent(date: str, kind: str) -> bool:
    cur = await _conn().execute(
        "SELECT 1 FROM sent_log WHERE date = ? AND kind = ?", (date, kind)
    )
    return await cur.fetchone() is not None


# --------------------------------------------------------------------------- #
# llm_memory / llm_turns — память диалога с LLM
# --------------------------------------------------------------------------- #
async def get_memory() -> dict[str, Any] | None:
    cur = await _conn().execute("SELECT * FROM llm_memory WHERE id = 1")
    row = await cur.fetchone()
    return dict(row) if row else None


@_writer
async def set_memory(summary: str) -> None:
    await _conn().execute(
        "INSERT INTO llm_memory (id, summary, updated_at) VALUES (1, ?, datetime('now')) "
        "ON CONFLICT(id) DO UPDATE SET summary = excluded.summary, updated_at = excluded.updated_at",
        (summary,),
    )
    await _conn().commit()


@_writer
async def add_turn(role: str, content: str) -> None:
    await _conn().execute(
        "INSERT INTO llm_turns (role, content, ts) VALUES (?, ?, datetime('now'))",
        (role, content),
    )
    await _conn().commit()
    # Держим только последние 30 реплик.
    await _conn().execute(
        "DELETE FROM llm_turns WHERE id NOT IN "
        "(SELECT id FROM llm_turns ORDER BY id DESC LIMIT 30)"
    )
    await _conn().commit()


async def recent_turns(limit: int = 8) -> list[dict[str, Any]]:
    cur = await _conn().execute(
        "SELECT role, content FROM llm_turns ORDER BY id DESC LIMIT ?", (limit,)
    )
    rows = [dict(r) for r in await cur.fetchall()]
    rows.reverse()
    return rows


# --------------------------------------------------------------------------- #
# channel_settings — mute-флаги и chat_id по платформам
# --------------------------------------------------------------------------- #
@_writer
async def set_channel(
    platform: str, *, muted: bool | None = None, chat_id: str | None = None
) -> None:
    """Upsert настроек канала. None-поля не трогаются."""
    await _conn().execute(
        "INSERT OR IGNORE INTO channel_settings (platform, muted) VALUES (?, 0)", (platform,)
    )
    updates: dict[str, Any] = {}
    if muted is not None:
        updates["muted"] = int(muted)
    if chat_id is not None:
        updates["chat_id"] = chat_id
    if updates:
        cols = ", ".join(f"{k} = ?" for k in updates)
        await _conn().execute(
            f"UPDATE channel_settings SET {cols} WHERE platform = ?",
            (*updates.values(), platform),
        )
    await _conn().commit()


async def is_muted(platform: str) -> bool:
    cur = await _conn().execute(
        "SELECT muted FROM channel_settings WHERE platform = ?", (platform,)
    )
    row = await cur.fetchone()
    return bool(row and row["muted"])


async def get_chat_id(platform: str) -> str | None:
    cur = await _conn().execute(
        "SELECT chat_id FROM channel_settings WHERE platform = ?", (platform,)
    )
    row = await cur.fetchone()
    return row["chat_id"] if row else None


# --------------------------------------------------------------------------- #
# msg_refs — ссылки на рассылочные сообщения по платформам (для синхр. кнопок)
# --------------------------------------------------------------------------- #
@_writer
async def set_msg_ref(
    date: str, kind: str, platform: str, chat_id: str, message_id: str, text: str = ""
) -> None:
    """Запомнить, куда (platform/chat/message_id) ушла рассылка kind за дату date.
    text нужен Max (PUT /messages переписывает сообщение целиком при снятии кнопки)."""
    await _conn().execute(
        "INSERT OR REPLACE INTO msg_refs (date, kind, platform, chat_id, message_id, text) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (date, kind, platform, str(chat_id), str(message_id), text),
    )
    await _conn().commit()


async def get_msg_refs(date: str, kind: str) -> list[dict[str, Any]]:
    cur = await _conn().execute(
        "SELECT * FROM msg_refs WHERE date = ? AND kind = ?", (date, kind)
    )
    return [dict(r) for r in await cur.fetchall()]


# --------------------------------------------------------------------------- #
# photos — фото «до/после» для AI-анализа осанки
# --------------------------------------------------------------------------- #
@_writer
async def add_photo(role: str, path: str, note: str = "") -> None:
    await _conn().execute(
        "INSERT INTO photos (ts, role, path, note) VALUES (datetime('now'), ?, ?, ?)",
        (role, path, note),
    )
    await _conn().commit()


async def latest_photo(role: str) -> dict[str, Any] | None:
    cur = await _conn().execute(
        "SELECT * FROM photos WHERE role = ? ORDER BY id DESC LIMIT 1", (role,)
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def completed_program_day(state: dict, before: str) -> bool:
    """One fully completed calendar date since entering this lesson; ignore future rows."""
    cur = await _conn().execute(
        "SELECT 1 FROM daily_logs l WHERE l.day_number=? AND l.date>=? AND l.date<? "
        "AND l.morning_done=1 AND l.ping_done=1 AND l.evening_done=1 AND l.habits_status='yes' "
        "AND EXISTS (SELECT 1 FROM reading_events r WHERE r.day=l.day_number "
        "AND r.status='done' AND r.date>=? AND r.date<=l.date) LIMIT 1",
        (state['current_day'], state.get('day_started_date') or state['started_at'], before,
         state.get('day_started_date') or state['started_at']))
    return await cur.fetchone() is not None


async def day_checklist(state: dict, today: str) -> dict[str, bool]:
    log = await get_log(today) or {}
    if log.get('day_number') != state['current_day']:
        log = {}
    reading = await reading_status(state['current_day'])
    since = state.get('day_started_date') or state['started_at']
    return {'утреннее движение — /today': bool(log.get('morning_done')),
            'дневная пауза — /ping': bool(log.get('ping_done')),
            'урок дочитан — /theory': bool(reading['read_at'] and since <= reading['read_at'] <= today),
            'движение выполнено полностью — /evening': log.get('habits_status') == 'yes',
            'вечерний опрос закончен — /evening': bool(log.get('evening_done'))}


@_writer
async def rollover_program(timezone: str) -> dict:
    """Serialize completion check and day change with check-in writes."""
    from bot import planner
    state = await get_state()
    updates = await planner.morning_rollover(state, timezone)
    if updates:
        columns = ', '.join(f'{k}=?' for k in updates)
        await _conn().execute(f'UPDATE user_state SET {columns} WHERE id=1', tuple(updates.values()))
        await _conn().commit()
        state.update(updates)
    return state


@_writer
async def reset_all_progress(today: str) -> None:
    """Owner-authorized full reset; keep channel bindings, content and delivery deduplication."""
    for table in ('daily_logs', 'reading_progress', 'reading_events', 'checkin_drafts',
                  'llm_memory', 'llm_turns', 'msg_refs', 'photos'):
        await _conn().execute(f'DELETE FROM {table}')
    await _conn().execute(
        'UPDATE user_state SET current_day=1, streak=0, paused=0, week_extra_days=0, '
        'last_morning_date=?, last_log_date=NULL, started_at=?, day_started_date=? WHERE id=1',
        (today, today, today))
    await _conn().commit()
