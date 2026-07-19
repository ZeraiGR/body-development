"""LLM-бэкенд с fallback. Основной — локальная Ollama (см. docs/LLM_INTEGRATION_RESEARCH.md).

Контракт: generate() возвращает текст ответа либо None (backend=none или сбой).
Вызывающий при None откатывается на шаблон — бот никогда не молчит и не ломается.
"""
from __future__ import annotations

import logging

import aiohttp

from config import config

log = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=180)  # локальная 32B может думать; 0B-холодный старт


async def generate(
    system: str,
    user: str,
    history: list[dict] | None = None,
    *,
    max_tokens: int = 700,
) -> str | None:
    """Текст ответа или None (→ fallback на шаблоны)."""
    backend = config.llm_backend
    if backend in ("", "none", "off"):
        return None
    try:
        if backend == "ollama":
            return await _ollama(system, user, history, max_tokens)
        if backend == "openrouter" and config.openrouter_api_key:
            return await _openrouter(system, user, history, max_tokens)
        if backend == "gemini" and config.gemini_api_key:
            return await _gemini(system, user, history, max_tokens)
        log.warning("LLM backend=%s не настроен (нет ключа) — fallback", backend)
        return None
    except Exception as exc:  # любая ошибка → не ронять бот
        log.warning("LLM generate (%s) не удалось: %s — fallback", backend, exc)
        return None


async def _ollama(system, user, history, max_tokens):
    messages = [{"role": "system", "content": system}]
    if history:
        messages += history
    messages.append({"role": "user", "content": user})
    payload = {
        "model": config.ollama_model,
        "messages": messages,
        "stream": False,
        "think": False,  # Qwen3: отключаем режим «рассуждения» — ответ сразу в content, быстро
        "options": {"num_predict": max_tokens, "temperature": 0.7},
    }
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
        async with session.post(f"{config.ollama_host}/api/chat", json=payload) as resp:
            data = await resp.json(content_type=None)
    if not data or "message" not in data:
        raise RuntimeError(f"пустой/некорректный ответ Ollama: {str(data)[:200]}")
    return (data["message"].get("content") or "").strip() or None


# Облачные бэкенды — скелеты (включаются при наличии ключа). Формат OpenAI-compatible.
async def _openrouter(system, user, history, max_tokens):
    messages = [{"role": "system", "content": system}] + (history or []) + [{"role": "user", "content": user}]
    payload = {"model": "qwen/qwen3-32b:free", "messages": messages, "max_tokens": max_tokens}
    headers = {"Authorization": f"Bearer {config.openrouter_api_key}"}
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers
        ) as resp:
            data = await resp.json(content_type=None)
    return (data["choices"][0]["message"]["content"] or "").strip() or None


async def _gemini(system, user, history, max_tokens):
    # Gemini имеет свой формат; реализуется при выборе облачного пути.
    log.warning("Gemini backend пока не реализован — fallback")
    return None
