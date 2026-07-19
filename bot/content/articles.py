"""Загрузчик статей из data/articles/day_N.json.

Каждый день — отдельный JSON-файл. Добавить/обновить день = перезаписать один файл.
"""
from __future__ import annotations

import json
from pathlib import Path

_ARTICLES_DIR = Path(__file__).parent.parent.parent / "data" / "articles"


def _load_all() -> list[dict]:
    articles: list[dict] = []
    if _ARTICLES_DIR.exists():
        for f in sorted(_ARTICLES_DIR.glob("day_*.json")):
            try:
                articles.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
    articles.sort(key=lambda a: a.get("day", 0))
    return articles


ARTICLES = _load_all()


def get_article(day: int) -> dict | None:
    if not ARTICLES:
        return None
    if day < 1:
        day = 1
    if day > len(ARTICLES):
        day = len(ARTICLES)
    return next((a for a in ARTICLES if a["day"] == day), None)
