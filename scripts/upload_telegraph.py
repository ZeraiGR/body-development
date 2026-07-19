"""Разовая загрузка 30 статей курса на Telegraph и сохранение ссылок в БД.

Запуск из корня проекта (обязательно через интерпретатор venv):
    .venv/bin/python scripts/upload_telegraph.py

Особенности:
  - резюме: дни, уже загруженные в БД, пропускаются (можно перезапускать);
  - ссылки сохраняются в БД сразу после каждой статьи (прогресс не теряется);
  - токен аккаунта Telegraph сохраняется в .env (TELEGRAPH_TOKEN), чтобы
    повторные запуски не плодили аккаунты;
  - между страницами пауза + автоповтор при FLOOD_WAIT;
  - нужен сетевой доступ к telegra.ph (через sing-box TUN или TG_PROXY).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import aiohttp  # noqa: E402

from config import config  # noqa: E402
from bot import db  # noqa: E402
from bot.content.articles import ARTICLES  # noqa: E402
from bot.content.quotes import QUOTES  # noqa: E402
from bot.telegraph import (  # noqa: E402
    _PAGE_DELAY,
    article_to_content,
    create_account,
    create_page,
)

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def save_token_to_env(token: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    out, found = [], False
    for ln in lines:
        if ln.startswith("TELEGRAPH_TOKEN="):
            out.append(f"TELEGRAPH_TOKEN={token}")
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"TELEGRAPH_TOKEN={token}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


async def main() -> None:
    await db.init_db(config.db_path)
    token = config.telegraph_token
    try:
        async with aiohttp.ClientSession() as session:
            if not token:
                token = await create_account(session, "BackRehabBot")
                save_token_to_env(token)
                print("ℹ️ Создан аккаунт Telegraph, токен сохранён в .env (TELEGRAPH_TOKEN).\n")

            uploaded = skipped = 0
            for article in ARTICLES:
                day = article["day"]
                if await db.get_telegraph_link(day):
                    skipped += 1
                    continue
                content = article_to_content(article, QUOTES.get(day))
                url = await create_page(session, token, article["title"], content)
                await db.set_telegraph_links([(day, url, article["title"])])  # сразу в БД
                uploaded += 1
                print(f"  ✅ день {day:>2}: {url}")
                await asyncio.sleep(_PAGE_DELAY)

        print(f"\nГотово. Загружено: {uploaded}, пропущено (уже было): {skipped}\n")
        for a in ARTICLES:
            link = await db.get_telegraph_link(a["day"])
            if link:
                print(f"  день {a['day']:>2}: {link}  —  {a['title']}")
    finally:
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
