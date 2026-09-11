"""Publish one current lesson and update its link/hash; preserve all other days.

Run from the repo root: .venv/bin/python -m scripts.reupload_article N
"""
from __future__ import annotations

import argparse
import asyncio

import aiohttp

from config import config
from bot import db, telegraph
from bot.content.articles import get_article


async def main(day: int) -> None:
    if not 1 <= day <= 30:
        raise ValueError('Номер дня должен быть от 1 до 30')
    article = get_article(day)
    if not config.telegraph_token:
        raise ValueError('Сначала настрой TELEGRAPH_TOKEN или запусти scripts/upload_telegraph.py')
    await db.init_db(config.db_path)
    try:
        async with aiohttp.ClientSession() as session:
            await telegraph.check_image_urls(session, [article])
            url = await telegraph.create_page(session, config.telegraph_token, article['title'], telegraph.article_to_content(article))
        await db.set_telegraph_links([(day, url, article['title'])])
        print(f'day {day}: {url}')
    finally:
        await db.close_db()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('day', type=int, choices=range(1, 31))
    asyncio.run(main(parser.parse_args().day))
