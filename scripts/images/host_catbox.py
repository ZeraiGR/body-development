"""Постоянный хостинг изображений на catbox.moe (НЕ litterbox — тот временный 72ч).

catbox.moe/main: бесплатно, без авторизации, навсегда. API: POST multipart
на https://catbox.moe/user/api.php с reqtype=fileupload + fileToUpload.
Возвращает URL вида https://files.catbox.moe/<hash>.png.

trust_env=False — чтобы игнорировать мёртвый env-прокси в shell.
"""
from __future__ import annotations

import os

import aiohttp

CATBOX_API = "https://catbox.moe/user/api.php"


async def upload(path: str) -> str:
    """Загрузить файл-картинку на catbox.moe, вернуть постоянный URL."""
    async with aiohttp.ClientSession(trust_env=False) as s:
        with open(path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("reqtype", "fileupload")
            data.add_field("fileToUpload", f, filename=os.path.basename(path))
            async with s.post(CATBOX_API, data=data, timeout=aiohttp.ClientTimeout(total=60)) as r:
                url = (await r.text()).strip()
    if not url.startswith("http"):
        raise RuntimeError(f"catbox upload failed: {url!r}")
    return url


if __name__ == "__main__":
    import asyncio, sys

    print(asyncio.run(upload(sys.argv[1])))
