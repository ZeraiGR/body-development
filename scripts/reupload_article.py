"""Перезалить статью дня N на Telegraph и обновить ссылку в БД.

Использование (с VPS, из корня проекта):
    .venv/bin/python -m scripts.reupload_article 1

Используется при переписывании статей (content overhaul): меняет body_markdown
в data/articles/day_N.json, этот скрипт создаёт новую страницу Telegraph и
обновляет telegraph_links, чтобы /theory N показывал свежую версию.
"""
from __future__ import annotations

import asyncio
import json
import sys

import aiohttp

from config import config
from bot import db, telegraph


async def main(day: int) -> None:
    await db.init_db(config.db_path)
    article = json.load(open(f"data/articles/day_{day}.json", encoding="utf-8"))
    async with aiohttp.ClientSession() as s:
        content = telegraph.article_to_content(article)
        url = await telegraph.create_page(s, config.telegraph_token, article["title"], content)
    # Обновить только одну ссылку (не трогая остальные дни).
    await db._conn().execute(
        "INSERT OR REPLACE INTO telegraph_links (day, url, title) VALUES (?, ?, ?)",
        (day, url, article["title"]),
    )
    await db._conn().commit()
    print(f"day {day}: {url}")
    await db.close_db()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("укажи номер дня: python -m scripts.reupload_article 1")
        sys.exit(1)
    asyncio.run(main(int(sys.argv[1])))
