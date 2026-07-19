"""Слой хранилища: SQLite (aiosqlite).

Схема заточена под однопользовательского бота — состояние хранится
в единственной строке user_state (id=1).

Таблицы:
  user_state       — current_day (1..30), streak, paused, week_extra_days,
                     last_log_date, started_at.
  daily_logs       — по строке на календарный день: pain/stiffness (1..10),
                     флаги утро/вечер/привычки, заметка.
  telegraph_links  — day -> url статьи теории.
"""
from __future__ import annotations

from typing import Any, Iterable

import aiosqlite

_db: aiosqlite.Connection | None = None


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
            pain          INTEGER,                    -- 1..10, NULL если не отвечал
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

        CREATE INDEX IF NOT EXISTS idx_logs_date ON daily_logs(date);
        """
    )
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
    if updates:
        columns = ", ".join(f"{k} = ?" for k in updates)
        await _conn().execute(
            f"UPDATE daily_logs SET {columns} WHERE date = ?",
            (*updates.values(), date),
        )
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
    cur = await _conn().execute(
        "SELECT url FROM telegraph_links WHERE day = ?", (day,)
    )
    row = await cur.fetchone()
    return row["url"] if row else None


async def set_telegraph_links(links: Iterable[tuple[int, str, str]]) -> None:
    """Перезаписать все ссылки (day, url, title)."""
    await _conn().executemany(
        "INSERT OR REPLACE INTO telegraph_links (day, url, title) VALUES (?, ?, ?)",
        list(links),
    )
    await _conn().commit()


# --------------------------------------------------------------------------- #
# sent_log — идемпотентность рассылок и catch-up при старте
# --------------------------------------------------------------------------- #
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


async def set_memory(summary: str) -> None:
    await _conn().execute(
        "INSERT INTO llm_memory (id, summary, updated_at) VALUES (1, ?, datetime('now')) "
        "ON CONFLICT(id) DO UPDATE SET summary = excluded.summary, updated_at = excluded.updated_at",
        (summary,),
    )
    await _conn().commit()


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
