"""VK-бот: минимальный клиент VK Bot API (aiohttp) + Long Poll + хендлеры.

Зеркало logic-слоя handlers.py для VK. Переиспользует общую логику
(db / messages / planner / llm / llm_context) — дублируется только транспорт
и диспетчер команд/колбэков. TG-бот (handlers.py) не трогается.

Однопользовательский: отвечает только VK_USER_ID (владельцу), прочих игнорирует
(приватный канал). Сообщения отправляются как plain text (markdown-маркеры
снимаются — VK не парсит TG-Markdown; эмодзи и структура сохраняются).

Long Poll запускается как asyncio-таск в одном цикле с aiogram — отдельный
процесс не нужен, БД (aiosqlite) одна, конкуренции за запись нет.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re

import aiohttp
from aiogram.types import InlineKeyboardMarkup

from bot import journey, db, llm, llm_context, messages, planner
from bot.bridge import settle, refresh_morning

log = logging.getLogger(__name__)

VK_API = "https://api.vk.com/method"
VK_V = "5.199"
_LP_WAIT = 25  # сек long-poll

_CHAT_LOCK = asyncio.Lock()  # сериализует LLM-диалог (как в handlers.py)


# --------------------------------------------------------------------------- #
# Утилиты: markdown → plain, конвертация клавиатур TG → VK
# --------------------------------------------------------------------------- #
def _strip_md(s: str) -> str:
    """Снять TG-markdown-маркеры (**b*, *i*, _i_, `code`) — VK не парсит их."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"\1", s)
    s = re.sub(r"\*([^*\n]+?)\*", r"\1", s)
    s = re.sub(r"`([^`\n]+?)`", r"\1", s)
    return s


def _color_for(label: str) -> str:
    if label.startswith("✅"):
        return "positive"
    if label.startswith(("⏩", "⏰", "😴", "❌")):
        return "negative"
    return "secondary"


def kb_to_vk(kb: InlineKeyboardMarkup | None) -> str | None:
    """aiogram InlineKeyboardMarkup → JSON-строка inline-клавиатуры VK.

    callback-кнопки: payload = json.dumps(callback_data) (VK требует строку).
    url-кнопки (теория): type=link.
    """
    if kb is None:
        return None
    rows_out: list[list[dict]] = []
    for row in kb.inline_keyboard:
        vrow: list[dict] = []
        for btn in row:
            label = (btn.text or "")[:40]
            if getattr(btn, "url", None):
                # VK: тип для кнопки-ссылки — "open_link" (не "link"!).
                vrow.append({"action": {"type": "open_link", "label": label, "link": btn.url}})
            else:
                cd = btn.callback_data or ""
                vrow.append({
                    "action": {
                        "type": "callback",
                        "label": label,
                        "payload": json.dumps(cd, ensure_ascii=False),
                    },
                    "color": _color_for(btn.text or ""),
                })
        rows_out.append(vrow)
    return json.dumps({"inline": True, "buttons": rows_out}, ensure_ascii=False)


def _parse_payload(payload) -> str:
    """VK возвращает payload строкой (JSON, который мы положили). Достаём callback_data."""
    if payload is None:
        return ""
    if isinstance(payload, (dict, list)):
        return json.dumps(payload, ensure_ascii=False)
    s = str(payload)
    try:
        decoded = json.loads(s)
        if isinstance(decoded, str):
            return decoded
        return json.dumps(decoded, ensure_ascii=False)
    except (ValueError, TypeError):
        return s


# --------------------------------------------------------------------------- #
# VK-бот
# --------------------------------------------------------------------------- #
class VKBot:
    def __init__(self, token: str, owner_user_id: int) -> None:
        self.token = token
        self.owner = owner_user_id
        self.session: aiohttp.ClientSession | None = None
        self._group_id: int | None = None
        self._rnd = random.Random()

    async def start(self) -> None:
        """Инициализация: сессия + group_id (для Long Poll)."""
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        # group_id из самого токена (групповой токен знает свою группу).
        info = await self._call("groups.getById")
        # Групповой токен: response = {"groups":[{"id":...}], "profiles":[]}
        # (на случай иной формы — проверяем и "items", и список).
        grp = None
        if isinstance(info, dict):
            grp = info.get("groups") or info.get("items")
        elif isinstance(info, list):
            grp = info
        if not grp:
            raise RuntimeError(f"Не удалось определить group_id по VK_TOKEN (ответ: {info!r})")
        self._group_id = int(grp[0]["id"])
        log.info("VK-бот инициализирован: group_id=%s, owner=%s", self._group_id, self.owner)

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    # ----------------------------- API вызовы ----------------------------- #
    async def _call(self, method: str, **params) -> dict | list:
        params = {"v": VK_V, "access_token": self.token, **params}
        async with self.session.post(f"{VK_API}/{method}", data=params) as resp:
            data = await resp.json(content_type=None)
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            log.warning("VK API %s error %s: %s", method, err.get("error_code"), err.get("error_msg"))
            return data  # вызывающий сам решает, что с ошибкой делать
        return data.get("response", data) if isinstance(data, dict) else data

    async def send(self, text: str, tg_kb: InlineKeyboardMarkup | None = None) -> None:
        """Отправить сообщение владельцу (peer_id = owner). Best-effort для scheduler."""
        await self._send_to(self.owner, text, tg_kb)

    async def _send_to(self, peer_id: int, text: str, tg_kb: InlineKeyboardMarkup | None = None) -> int | None:
        params = {
            "peer_id": peer_id,
            "message": _strip_md(text),
            "random_id": self._rnd.randint(0, 2**31 - 1),
        }
        kb = kb_to_vk(tg_kb)
        if kb:
            params["keyboard"] = kb
        resp = await self._call("messages.send", **params)
        if isinstance(resp, dict) and "error" in resp:
            return None
        return resp[0] if isinstance(resp, list) and resp else (resp if isinstance(resp, int) else None)

    async def _edit(self, peer_id: int, cmid: int, text: str | None, tg_kb: InlineKeyboardMarkup | None) -> None:
        """Редактировать сообщение (текст и/или клавиатура). text=None — оставить текст."""
        params: dict = {"peer_id": peer_id, "conversation_message_id": cmid}
        if text is not None:
            params["message"] = _strip_md(text)
        kb = kb_to_vk(tg_kb)
        if kb is not None:
            params["keyboard"] = kb
        await self._call("messages.edit", **params)

    async def _answer_event(self, event_id: str, user_id: int, peer_id: int, toast: str) -> None:
        if not toast:
            return
        await self._call(
            "messages.sendMessageEventAnswer",
            event_id=event_id,
            user_id=user_id,
            peer_id=peer_id,
            event_data=json.dumps({"type": "show_snackbar", "text": toast}, ensure_ascii=False),
        )

    # ----------------------------- Long Poll ------------------------------ #
    async def run_polling(self) -> None:
        """Бесконечный Long Poll. Перезапуск key/ts при устаревании."""
        assert self._group_id, "VKBot.start() не вызван"
        server = key = ts = None
        while True:
            try:
                if not (server and key and ts):
                    lp = await self._call("groups.getLongPollServer", group_id=self._group_id)
                    if not isinstance(lp, dict) or "server" not in lp:
                        log.error("VK getLongPollServer неудача: %s", lp)
                        await asyncio.sleep(5)
                        continue
                    server, key, ts = lp["server"], lp["key"], lp["ts"]
                async with self.session.get(
                    server, params={"act": "a_check", "key": key, "ts": ts, "wait": _LP_WAIT}
                ) as resp:
                    data = await resp.json(content_type=None)
                if data.get("failed"):
                    code = data["failed"]
                    if code == 1:  # ts устарел
                        ts = data.get("ts", ts)
                        continue
                    # 2/3/4 — пересоздать key
                    server = key = ts = None
                    continue
                ts = data.get("ts", ts)
                updates = data.get("updates", [])
                if updates:
                    log.info("VK longpoll: получено событий: %d", len(updates))
                for update in updates:
                    try:
                        await self._dispatch(update)
                    except Exception:
                        log.exception("VK dispatch error (update=%s)", update.get("type"))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("VK longpoll error, переподключение через 5с")
                await asyncio.sleep(5)

    async def _dispatch(self, update: dict) -> None:
        utype = update.get("type")
        log.info("VK event: type=%s", utype)
        obj = update.get("object", {})
        if utype == "message_new":
            msg = obj.get("message", {})
            await self._on_message(msg)
        elif utype == "message_event":
            await self._on_event(obj)

    # --------------------------- сообщения (команды) ---------------------- #
    async def _on_message(self, msg: dict) -> None:
        peer_id = msg.get("peer_id")
        text = (msg.get("text") or "").strip()
        log.debug("VK message received")
        if peer_id != self.owner:
            log.info("VK: отброшено (peer %s != owner %s)", peer_id, self.owner)
            return  # приватный канал: только владелец
        if not text:
            return
        # команда может приходить с payload-кнопкой тоже, но текст — основной путь
        cmd = text.lstrip("/").split(maxsplit=1)
        name = cmd[0].lower().split("@")[0] if cmd else ""
        args = cmd[1].strip() if len(cmd) > 1 else ""

        handlers = {
            "start": lambda: self._reply(messages.welcome_text()),
            "help": lambda: self._reply(self._help_text()),
            "status": self._cmd_status,
            "report": lambda: self._cmd_report(args),
            "pause": self._cmd_pause,
            "resume": self._cmd_resume,
            "next": self._cmd_next,
            "hard": self._cmd_hard,
            "reset": self._cmd_reset,
            "today": self._cmd_today,
            "theory": lambda: self._cmd_theory(args),
            "day": lambda: self._cmd_theory(args),
            "evening": self._cmd_evening,
            "ping": self._cmd_ping,
            "remember": self._cmd_remember,
            "mute": self._cmd_mute,
            "unmute": self._cmd_unmute,
            "lessons": self._cmd_lessons,
            "continue": lambda: self._cmd_continue(args),
            "goto": lambda: self._cmd_goto(args),
        }
        if name in handlers:
            await handlers[name]()
        elif name == "chat":
            await self._llm_chat(args)
        else:
            # свободный текст → LLM (как fallback в TG)
            await self._llm_chat(text)

    def _help_text(self) -> str:
        return (
            "Команды:\n"
            "/status — где я сейчас (день/неделя/стрик)\n"
            "/today — утреннее сообщение дня вручную\n"
            "/evening — запустить вечерний опрос\n"
            "/ping — дневной микро-пинг\n"
            "/report [ГГГГ-ММ-ДД] — неделя до выбранной даты\n"
            "/chat <текст> — поговорить с ИИ (или просто напиши текст)\n"
            "/remember — обновить память ИИ\n"
            "/pause · /resume · /next · /hard · /reset — управление программой\n"
            "/goto N — открыть урок · /continue N — вернуться к уже открытому дню · /lessons — все темы\n"
            "/theory N — теория дня N (без N — текущий)"
        )

    async def _reply(self, text: str, tg_kb: InlineKeyboardMarkup | None = None) -> None:
        await self._send_to(self.owner, text, tg_kb)

    # --- конкретные команды (зеркало handlers.py) ---
    async def _cmd_status(self) -> None:
        await self._reply(await journey.status())

    async def _cmd_report(self, args: str = "") -> None:
        await self._reply(await journey.report(args))

    async def _cmd_pause(self) -> None:
        await db.update_state(paused=1)
        await self._reply("⏸ Пауза включена. Рассылки не придут, пока не нажмёшь /resume.")

    async def _cmd_resume(self) -> None:
        await db.update_state(paused=0)
        await self._reply("▶️ Снова в строю. Продолжаем 💪")

    async def _cmd_next(self) -> None:
        await self._reply(await journey.next_day())

    async def _cmd_hard(self) -> None:
        extra = 2
        await db.update_state(week_extra_days=extra)
        await self._reply(messages.hard_confirm_text(extra))

    async def _cmd_reset(self) -> None:
        await self._reply(await journey.reset())

    async def _cmd_today(self) -> None:
        text, kb = await journey.today()
        await self._reply(text, kb)

    async def _cmd_theory(self, args: str) -> None:
        text, kb = await journey.lesson(args.strip())
        await self._reply(text, kb)

    async def _cmd_goto(self, args: str) -> None:
        await self._cmd_theory(args)

    async def _cmd_lessons(self) -> None:
        text, kb = await journey.lesson_list()
        await self._reply(text, kb)

    async def _cmd_continue(self, args: str) -> None:
        await self._reply(await journey.continue_from(args.strip()))

    async def _cmd_evening(self) -> None:
        text, kb = await journey.evening()
        await self._reply(text, kb)

    async def _cmd_ping(self) -> None:
        text, kb = messages.day_ping_text()
        await self._reply(text, kb)

    async def _cmd_remember(self) -> None:
        new = await llm_context.summarize_text()
        if not new:
            await self._reply("Пока нечего запоминать — давай сначала поболтаем через /chat 🙂")
            return
        await db.set_memory(new)
        await self._reply("🧠 Память обновлена:\n\n" + new)

    async def _cmd_mute(self) -> None:
        await db.set_channel("vk", muted=True)
        await self._reply("🔇 Рассылки в VK отключены. Команды работают. /unmute — вернуть.")

    async def _cmd_unmute(self) -> None:
        await db.set_channel("vk", muted=False)
        await self._reply("🔔 Рассылки в VK снова включены.")

    async def _llm_chat(self, user_text: str) -> None:
        if not user_text:
            await self._reply("Напиши так: /chat <твоё сообщение>.")
            return
        async with _CHAT_LOCK:
            await db.add_turn("user", user_text)
            system, history, user = await llm_context.build_messages(user_text)
            reply = await llm.generate(system, user, history)
            if reply:
                await db.add_turn("assistant", reply)
                await self._reply(reply)
            else:
                await self._reply(messages.llm_offline_text())

    # --------------------------- колбэки (кнопки) ------------------------- #
    async def _on_event(self, obj: dict) -> None:
        peer_id = obj.get("peer_id")
        user_id = obj.get("user_id")
        if user_id != self.owner:
            return
        cmid = obj.get("conversation_message_id")
        event_id = obj.get("event_id", "")
        data = _parse_payload(obj.get("payload"))

        async def toast(t: str) -> None:
            await self._answer_event(event_id, user_id, peer_id, t)

        if data.startswith(("learn:", "move:", "check:", "pausemove:")):
            await toast("")
            text, kb = await journey.action(data)
            if data.startswith("move:" + planner.today_iso(config_schedule_tz()) + ":") and (await db.get_log(planner.today_iso(config_schedule_tz())) or {}).get("morning_done"):
                await refresh_morning(planner.today_iso(config_schedule_tz()))
            await self._reply(text, kb)
            return
        if data in ("morning:done", "morning:later", "theory:done") or data.startswith(("pl:", "loc:", "habits:")):
            await toast("Старая кнопка. Открой /today, /theory или /evening.")
            return

        if data in ("ping:done", "ping:skip"):
            await toast("Старая кнопка. Открой /ping и отметь сегодняшнюю паузу.")
        elif data == "hard":
            extra = 2
            await db.update_state(week_extra_days=extra)
            await self._reply(messages.hard_confirm_text(extra))
            await self._edit(peer_id, cmid, None, None)
            await toast("Задерживаемся 🌿")


def config_schedule_tz() -> str:
    from config import config
    return config.schedule.timezone
