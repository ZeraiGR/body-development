"""Клиент Telegraph API (через aiohttp) — устойчивая загрузка + красивая вёрстка.

Особенности:
  - article_to_content() собирает «богатую» страницу: заголовки h3, главный
    факт жирным, абзацы, углубление курсивом, цитату Move Your DNA блок-цитатой.
  - create_page() автоматически ждёт и повторяет при FLOOD_WAIT_N.
  - upload_articles() делает паузу между страницами, чтобы не нарываться на
    flood-control Telegraph.
"""
from __future__ import annotations

import asyncio
import json
import re

import aiohttp

API = "https://api.telegra.ph"
DEFAULT_AUTHOR = "Спина: курс"
_PAGE_DELAY = 2.0  # сек между createPage — против FLOOD_WAIT
_FLOOD = re.compile(r"FLOOD_WAIT_(\d+)")


async def create_account(
    session: aiohttp.ClientSession, short_name: str, author_name: str = DEFAULT_AUTHOR
) -> str:
    payload = {"short_name": short_name[:32], "author_name": author_name[:128]}
    async with session.post(f"{API}/createAccount", data=payload) as resp:
        data = await resp.json(content_type=None)
    if not data.get("ok"):
        raise RuntimeError(f"Telegraph createAccount failed: {data}")
    return data["result"]["access_token"]


def _parse_inline(text: str) -> list:
    """Разобрать инлайн-разметку (**b**, *i*/_i_, `code`) в children для Telegraph."""
    patterns = [
        (re.compile(r"\*\*(.+?)\*\*"), "b"),
        (re.compile(r"__(.+?)__"), "b"),
        (re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)"), "i"),
        (re.compile(r"(?<!\w)_([^_\n]+?)_(?!\w)"), "i"),
        (re.compile(r"`([^`\n]+?)`"), "code"),
    ]
    children: list = []
    pos = 0
    while pos < len(text):
        best = None
        for rx, tag in patterns:
            m = rx.search(text, pos)
            if m and (best is None or m.start() < best[0].start()):
                best = (m, tag)
        if best is None:
            if text[pos:]:
                children.append(text[pos:])
            break
        m, tag = best
        if m.start() > pos:
            children.append(text[pos:m.start()])
        children.append({"tag": tag, "children": [m.group(1)]})
        pos = m.end()
    return children or [text]


def _is_block_special(line: str) -> bool:
    s = line.strip()
    return (
        s.startswith("#")
        or s.startswith("> ")
        or s == ">"
        or s.startswith("|")
        or s.startswith("```")
        or s.startswith("[РИСУНОК")
        or s.startswith("![")
        or s in ("---", "***", "___")
    )


def markdown_to_nodes(md: str) -> list[dict]:
    """Конвертер markdown → массив узлов Telegraph.

    Поддержка: ## / ### заголовки; > blockquote (подряд → один блок с <br>);
    **bold**, *italic*/_italic_, `code`; таблицы (|…|) — строками, шапка жирным
    (Telegraph не умеет таблицы); слоты [РИСУНОК: …] курсивом; ```-блоки построчно
    моноширинно; --- горизонтальная черта. Абзацы разделены пустой строкой.
    """
    lines = md.split("\n")
    nodes: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        s = line.strip()
        if s.startswith("```"):
            i += 1
            block: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            for bl in block:
                if bl.strip():
                    nodes.append({"tag": "p", "children": [{"tag": "code", "children": [bl]}]})
            continue
        if s.startswith("### "):
            nodes.append({"tag": "h4", "children": _parse_inline(s[4:])})
            i += 1
            continue
        if s.startswith("## "):
            nodes.append({"tag": "h3", "children": _parse_inline(s[3:])})
            i += 1
            continue
        if s.startswith("# "):
            nodes.append({"tag": "h3", "children": _parse_inline(s[2:])})
            i += 1
            continue
        if s.startswith("> "):
            qlines: list[str] = []
            while i < len(lines) and lines[i].startswith("> "):
                qlines.append(lines[i][2:])
                i += 1
            children: list = []
            for q in qlines:
                if children:
                    children.append({"tag": "br", "children": []})
                children.extend(_parse_inline(q))
            nodes.append({"tag": "blockquote", "children": children})
            continue
        if s.startswith("|"):
            rows: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            for idx, r in enumerate(rows):
                cells = [c.strip() for c in r.strip("|").split("|")]
                if cells and all(set(c) <= set("-: ") for c in cells):
                    continue
                joined = "  ·  ".join(cells)
                if idx == 0:
                    nodes.append({"tag": "p", "children": [{"tag": "b", "children": _parse_inline(joined)}]})
                else:
                    nodes.append({"tag": "p", "children": _parse_inline(joined)})
            continue
        if s.startswith("![]") or s.startswith("!["):
            m = re.match(r"^!\[([^\]]*)\]\((https?://[^\s)]+)\)", s)
            if m:
                nodes.append({"tag": "img", "attrs": {"src": m.group(2)}})
                if m.group(1).strip():
                    nodes.append({"tag": "p", "children": [{"tag": "i", "children": [m.group(1)]}]})
            else:
                nodes.append({"tag": "p", "children": [{"tag": "i", "children": [s]}]})
            i += 1
            continue
        if s.startswith("[РИСУНОК"):
            nodes.append({"tag": "p", "children": [{"tag": "i", "children": ["🖼 " + s]}]})
            i += 1
            continue
        if s in ("---", "***", "___"):
            nodes.append({"tag": "hr", "children": []})
            i += 1
            continue
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not _is_block_special(lines[i]):
            para.append(lines[i])
            i += 1
        text = " ".join(p.strip() for p in para)
        nodes.append({"tag": "p", "children": _parse_inline(text)})
    return nodes


def article_to_content(article: dict, quote: dict | None = None) -> list[dict]:
    """Собрать страницу Telegraph из статьи.

    Новый формат (article['body_markdown']) → рендер markdown-тела целиком.
    Старый формат (green/paragraphs/yellow) → backwards-compat.
    Опциональная цитата книги добавляется в конец.
    """
    if article.get("body_markdown"):
        content = markdown_to_nodes(article["body_markdown"])
    else:
        content = [
            {"tag": "h3", "children": ["🟢 Главный факт"]},
            {"tag": "p", "children": [{"tag": "b", "children": [article["green"]]}]},
        ]
        for para in article.get("paragraphs", []):
            if para.startswith("## "):
                content.append({"tag": "h3", "children": [para[3:]]})
            else:
                content.append({"tag": "p", "children": [para]})
        content.append({"tag": "h3", "children": ["🟡 Углубление"]})
        content.append({"tag": "p", "children": [{"tag": "i", "children": [article["yellow"]]}]})
    if quote and not article.get("body_markdown"):
        content.append({"tag": "h3", "children": ["📖 Move Your DNA"]})
        content.append({"tag": "blockquote", "children": [quote["concept"]]})
        content.append(
            {"tag": "blockquote", "children": [{"tag": "i", "children": [quote["quote"]]}]}
        )
        content.append(
            {"tag": "p", "children": [{"tag": "i", "children": [
                f"— Katy Bowman, Move Your DNA, стр. {quote['page']}"
            ]}]}
        )
    return content


async def create_page(
    session: aiohttp.ClientSession,
    token: str,
    title: str,
    content: list[dict],
    author_name: str = DEFAULT_AUTHOR,
) -> str:
    """createPage с автоповтором при FLOOD_WAIT_N."""
    payload = {
        "access_token": token,
        "title": title[:256],
        "author_name": author_name[:128],
        "content": json.dumps(content, ensure_ascii=False),
        "return_content": "false",
    }
    for _attempt in range(6):
        async with session.post(f"{API}/createPage", data=payload) as resp:
            data = await resp.json(content_type=None)
        if data.get("ok"):
            return data["result"]["url"]
        err = data.get("error", "")
        m = _FLOOD.search(err)
        if m:
            await asyncio.sleep(int(m.group(1)) + 1)
            continue
        raise RuntimeError(f"Telegraph createPage failed for {title!r}: {data}")
    raise RuntimeError(f"FLOOD_WAIT: превышены попытки для {title!r}")


async def upload_articles(
    articles: list[dict],
    quotes: dict[int, dict] | None = None,
    token: str | None = None,
    short_name: str = "BackRehabBot",
    page_delay: float = _PAGE_DELAY,
) -> tuple[str, list[tuple[int, str, str]]]:
    """Загрузить статьи. Возвращает (access_token, [(day, url, title), ...]).

    Между страницами — пауза page_delay; при FLOOD_WAIT create_page сам ждёт.
    """
    quotes = quotes or {}
    async with aiohttp.ClientSession() as session:
        if not token:
            token = await create_account(session, short_name)
        links: list[tuple[int, str, str]] = []
        for article in articles:
            content = article_to_content(article, quotes.get(article["day"]))
            url = await create_page(session, token, article["title"], content)
            links.append((article["day"], url, article["title"]))
            await asyncio.sleep(page_delay)
        return token, links
