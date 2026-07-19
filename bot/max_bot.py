"""MAX-бот: клиент Max Bot API (aiohttp) + Long Poll + хендлеры.

Зеркало logic-слоя handlers.py для мессенджера MAX. Переиспользует
db / messages / planner / llm / llm_context — дублируется только транспорт
и диспетчер команд/колбэков. TG/VK не трогаются.

Однопользовательский: owner chat_id авто-learnится по первому `bot_started`
(или входящему сообщению) и сохраняется в БД; далее бот отвечает только ему.
Markdown MAX поддерживает (format:"markdown").

Long Poll (`GET /updates`) запускается asyncio-таском в одном цикле с TG/VK.
API: https://platform-api2.max.ru, авторизация — заголовок `Authorization: <token>`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
from pathlib import Path

import aiohttp
from aiogram.types import InlineKeyboardMarkup

from bot import db, llm, llm_context, messages, planner
from bot.bridge import settle

log = logging.getLogger(__name__)

MAX_API = "https://platform-api2.max.ru"
_LP_WAIT = 30  # сек long-poll
_CHAT_LOCK = asyncio.Lock()


def _max_ssl_context() -> "ssl.SSLContext":
    """SSL-контекст с российским корневым УЦ (Минцифры).

    Сертификат platform-api2.max.ru подписан «Russian Trusted Root CA», которого
    нет в стандартном trust-store. Подгружаем его из bot/assets/.
    """
    ctx = ssl.create_default_context()
    ru = Path(__file__).resolve().parent / "assets" / "russian_root_ca.pem"
    if ru.exists():
        ctx.load_verify_locations(cafile=str(ru))
    else:
        log.warning("Russian Trusted Root CA не найден: %s", ru)
    return ctx


# --------------------------------------------------------------------------- #
# Конвертация клавиатур TG → MAX
# --------------------------------------------------------------------------- #
def kb_to_max(kb: InlineKeyboardMarkup | None) -> list[dict] | None:
    """aiogram InlineKeyboardMarkup → attachment inline_keyboard для MAX.

    Структура (по Python-клиенту Max): payload.buttons = list[list[button]] (2D,
    ряды кнопок). Callback-кнопка: {type:"callback", text, payload:<данные>}.
    Link-кнопка: {type:"link", text, url}.
    """
    if kb is None:
        return None
    buttons_2d: list[list[dict]] = []
    for row in kb.inline_keyboard:
        btns: list[dict] = []
        for btn in row:
            label = (btn.text or "")[:60]
            if getattr(btn, "url", None):
                btns.append({"type": "link", "text": label, "url": btn.url})
            else:
                cd = (btn.callback_data or "")[:64]
                btns.append({"type": "callback", "text": label, "payload": cd})
        buttons_2d.append(btns)
    return [{"type": "inline_keyboard", "payload": {"buttons": buttons_2d}}]


def _extract_chat_id(obj: dict) -> str | None:
    """Достать chat_id диалога из сообщения/события (несколько возможных путей)."""
    for path in (("recipient", "chat_id"), ("chat", "chat_id"), ("chat_id",)):
        v: object = obj
        for k in path:
            v = v.get(k) if isinstance(v, dict) else None
        if v is not None:
            return str(v)
    return None


def _msg_text(msg: dict) -> str:
    b = msg.get("body")
    if isinstance(b, dict):
        return b.get("text") or ""
    return msg.get("text") or ""


def _msg_user_id(msg: dict) -> str | None:
    s = msg.get("sender") or msg.get("user") or {}
    uid = s.get("user_id") or s.get("id")
    return str(uid) if uid is not None else None


# --------------------------------------------------------------------------- #
# MAX-бот
# --------------------------------------------------------------------------- #
class MaxBot:
    def __init__(self, token: str) -> None:
        self.token = token
        self.session: aiohttp.ClientSession | None = None
        self.owner_chat_id: str | None = None
        self._owner_user_id: str | None = None

    async def start(self) -> None:
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=70),
            connector=aiohttp.TCPConnector(ssl=_max_ssl_context()),
        )
        me = await self._call("GET", "/me")
        if isinstance(me, dict) and me.get("code") and me.get("message"):
            raise RuntimeError(f"MAX /me error: {me.get('code')} {me.get('message')}")
        name = me.get("name") if isinstance(me, dict) else None
        self.owner_chat_id = await db.get_chat_id("max")  # мог сохраниться ранее
        log.info("MAX-бот инициализирован: name=%s owner_chat=%s", name, self.owner_chat_id)

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    # ----------------------------- API вызовы ----------------------------- #
    async def _call(self, method: str, path: str, *, params=None, json_body=None) -> dict:
        headers = {"Authorization": self.token}
        async with self.session.request(
            method, f"{MAX_API}{path}", params=params, json=json_body, headers=headers
        ) as resp:
            try:
                data = await resp.json(content_type=None)
            except Exception:
                text = await resp.text()
                data = {"code": "non-json", "message": text[:200]}
        if isinstance(data, dict) and data.get("code") and data.get("message") and "updates" not in data:
            log.warning("MAX API %s %s → %s %s", method, path, data.get("code"), data.get("message"))
        return data

    async def send(self, text: str, tg_kb: InlineKeyboardMarkup | None = None):
        """Отправить владельцу (owner_chat_id). Для scheduler. None если owner неизвестен."""
        if not self.owner_chat_id:
            log.info("MAX send пропущен — owner_chat_id ещё не известен (стартани бота в MAX)")
            return None
        return await self._send_to(self.owner_chat_id, text, tg_kb)

    async def _send_to(self, chat_id: str, text: str, tg_kb: InlineKeyboardMarkup | None = None) -> str | None:
        body: dict = {"text": text[:4000], "format": "markdown"}
        att = kb_to_max(tg_kb)
        if att:
            body["attachments"] = att
        resp = await self._call("POST", "/messages", params={"chat_id": str(chat_id)}, json_body=body)
        # вернуть mid сообщения (нужно для msg_refs / синхронизации кнопок)
        try:
            return resp["message"]["body"]["mid"]
        except (KeyError, TypeError):
            return None

    async def _edit(self, message_id: str, text: str, tg_kb: InlineKeyboardMarkup | None = None) -> dict:
        body: dict = {"text": text[:4000], "format": "markdown"}
        att = kb_to_max(tg_kb)
        if att:
            body["attachments"] = att
        return await self._call("PUT", "/messages", params={"message_id": str(message_id)}, json_body=body)

    async def _answer_cb(self, callback_id, *, notification: str | None = None, message: dict | None = None) -> dict:
        body: dict = {}
        if notification is not None:
            body["notification"] = notification
        if message is not None:
            body["message"] = message
        return await self._call("POST", "/answers", params={"callback_id": str(callback_id)}, json_body=body)

    # ------------------------------ Long Poll ----------------------------- #
    async def run_polling(self) -> None:
        marker = None
        while True:
            try:
                params: dict = {
                    "timeout": _LP_WAIT,
                    "types": "bot_started,message_created,message_callback",
                }
                if marker:
                    params["marker"] = marker
                data = await self._call("GET", "/updates", params=params)
                if not isinstance(data, dict) or (data.get("code") and "updates" not in data):
                    await asyncio.sleep(5)
                    continue
                marker = data.get("marker", marker)
                for up in data.get("updates", []):
                    try:
                        await self._dispatch(up)
                    except Exception:
                        log.exception("MAX dispatch error (type=%s)", up.get("type"))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("MAX longpoll error, переподключение через 5с")
                await asyncio.sleep(5)

    async def _dispatch(self, up: dict) -> None:
        log.info("MAX raw update: %s", json.dumps(up, ensure_ascii=False)[:800])
        # MAX: тип в «update_type», объект события (message/callback) — на верхнем уровне.
        utype = up.get("update_type") or up.get("type")
        if utype == "bot_started":
            await self._on_started(up)
        elif utype == "message_created":
            await self._on_message(up.get("message") or {})
        elif utype == "message_callback":
            await self._on_callback(up.get("callback") or {})

    # --------------------------- owner / whitelist ------------------------ #
    async def _learn_owner(self, chat_id: str | None, user_id: str | None) -> bool:
        """Запомнить владельца при первом контакте. True если событие от владельца."""
        if chat_id and not self.owner_chat_id:
            self.owner_chat_id = chat_id
            await db.set_channel("max", chat_id=chat_id)
            log.info("MAX owner_chat_id learn: %s", chat_id)
        if user_id and not self._owner_user_id:
            self._owner_user_id = user_id
        if self._owner_user_id and user_id and user_id != self._owner_user_id:
            return False  # чужой
        return True

    async def _on_started(self, body: dict) -> None:
        chat_id = _extract_chat_id(body) or _extract_chat_id(body.get("chat") or {})
        user_id = _msg_user_id(body) or _msg_user_id(body.get("user") or {})
        await self._learn_owner(chat_id, user_id)
        cid = chat_id or self.owner_chat_id
        if cid:
            await self._send_to(cid, messages.welcome_text())
            await self._send_to(cid, "Напиши /status или /theory 1. /mute — отключить рассылки здесь.")

    # --------------------------- сообщения (команды) ---------------------- #
    async def _on_message(self, msg: dict) -> None:
        chat_id = _extract_chat_id(msg)
        user_id = _msg_user_id(msg)
        if not await self._learn_owner(chat_id, user_id):
            return  # чужой
        text = _msg_text(msg).strip()
        if not text:
            return
        cid = chat_id or self.owner_chat_id
        if not cid:
            return
        cmd = text.lstrip("/").split(maxsplit=1)
        name = cmd[0].lower().split("@")[0] if cmd else ""
        args = cmd[1].strip() if len(cmd) > 1 else ""

        handlers = {
            "start": lambda: self._reply(cid, messages.welcome_text()),
            "help": lambda: self._reply(cid, self._help()),
            "status": lambda: self._cmd_status(cid),
            "report": lambda: self._cmd_report(cid),
            "pause": lambda: self._cmd_pause(cid),
            "resume": lambda: self._cmd_resume(cid),
            "next": lambda: self._cmd_next(cid),
            "hard": lambda: self._cmd_hard(cid),
            "reset": lambda: self._cmd_reset(cid),
            "today": lambda: self._cmd_today(cid),
            "theory": lambda: self._cmd_theory(cid, args),
            "day": lambda: self._cmd_theory(cid, args),
            "evening": lambda: self._cmd_evening(cid),
            "ping": lambda: self._cmd_ping(cid),
            "remember": lambda: self._cmd_remember(cid),
            "mute": lambda: self._cmd_mute(cid),
            "unmute": lambda: self._cmd_unmute(cid),
            "goto": lambda: self._cmd_goto(cid, args),
        }
        if name in handlers:
            await handlers[name]()
        elif name == "chat":
            await self._llm_chat(cid, args)
        else:
            await self._llm_chat(cid, text)

    def _help(self) -> str:
        return (
            "Команды:\n"
            "/status — где я сейчас (день/неделя/стрик)\n"
            "/today — утреннее сообщение дня\n"
            "/evening — вечерний опрос · /ping — микро-пинг\n"
            "/report — недельный отчёт\n"
            "/theory N — теория дня N\n"
            "/chat <текст> — ИИ (или просто напиши текст)\n"
            "/remember — обновить память ИИ\n"
            "/mute — отключить рассылки в этом мессенджере · /unmute — вернуть\n"
            "/pause · /resume · /next · /hard · /reset — программа\n"
            "/goto N — перейти на любой день (1–30)"
        )

    async def _reply(self, cid: str, text: str, tg_kb: InlineKeyboardMarkup | None = None) -> None:
        await self._send_to(cid, text, tg_kb)

    async def _cmd_mute(self, cid: str) -> None:
        await db.set_channel("max", muted=True)
        await self._reply(cid, "🔇 Рассылки в MAX отключены. Команды продолжают работать. /unmute — вернуть.")

    async def _cmd_unmute(self, cid: str) -> None:
        await db.set_channel("max", muted=False)
        await self._reply(cid, "🔔 Рассылки в MAX снова включены.")

    async def _cmd_status(self, cid: str) -> None:
        st = await db.get_state()
        url = await db.get_telegraph_link(st["current_day"])
        await self._reply(cid, messages.status_text(st, url))

    async def _cmd_report(self, cid: str) -> None:
        tz = _tz()
        st = await db.get_state()
        logs = await db.logs_between(planner.date_iso(-6, tz), planner.today_iso(tz))
        await self._reply(cid, messages.weekly_report_text(logs, tz, st["current_day"]))

    async def _cmd_pause(self, cid: str) -> None:
        await db.update_state(paused=1)
        await self._reply(cid, "⏸ Пауза включена. /resume — снять.")

    async def _cmd_resume(self, cid: str) -> None:
        await db.update_state(paused=0)
        await self._reply(cid, "▶️ Снова в строю. 💪")

    async def _cmd_next(self, cid: str) -> None:
        st = await db.get_state()
        nd = min(st["current_day"] + 1, 30)
        await db.update_state(current_day=nd, last_morning_date=planner.today_iso(_tz()))
        await self._reply(cid, f"⏭ Перешёл на день {nd}.")

    async def _cmd_hard(self, cid: str) -> None:
        extra = 2
        await db.update_state(week_extra_days=extra)
        await self._reply(cid, messages.hard_confirm_text(extra))

    async def _cmd_reset(self, cid: str) -> None:
        await db.update_state(current_day=1, week_extra_days=0, last_morning_date=None,
                              last_log_date=None, streak=0, paused=0)
        await self._reply(cid, "🔄 Сброс. Снова День 1. 🌱")

    async def _cmd_today(self, cid: str) -> None:
        st = await db.get_state()
        url = await db.get_telegraph_link(st["current_day"])
        text, kb = messages.morning_text(st["current_day"], url)
        await self._reply(cid, text, kb)

    async def _cmd_theory(self, cid: str, args: str) -> None:
        day = int(args) if args.strip().isdigit() and 1 <= int(args) <= 30 else (await db.get_state())["current_day"]
        url = await db.get_telegraph_link(day)
        text, kb = messages.theory_text(day, url)
        await self._reply(cid, text, kb)

    async def _cmd_goto(self, cid: str, args: str) -> None:
        if not args.strip().isdigit():
            await self._reply(cid, "Напиши: /goto N (1–30). Например /goto 3.")
            return
        day = max(1, min(30, int(args.strip())))
        await db.update_state(current_day=day)
        url = await db.get_telegraph_link(day)
        await self._reply(cid, f"📍 Переключился на день {day}. /today — утреннее сообщение." + (f"\n🔗 {url}" if url else ""))

    async def _cmd_evening(self, cid: str) -> None:
        st = await db.get_state()
        text, kb = messages.evening_intro_text(st["current_day"])
        await self._reply(cid, text, kb)

    async def _cmd_ping(self, cid: str) -> None:
        text, kb = messages.day_ping_text()
        await self._reply(cid, text, kb)

    async def _cmd_remember(self, cid: str) -> None:
        new = await llm_context.summarize_text()
        if not new:
            await self._reply(cid, "Пока нечего запоминать — поболтаем через /chat 🙂")
            return
        await db.set_memory(new)
        await self._reply(cid, "🧠 Память обновлена:\n\n" + new)

    async def _llm_chat(self, cid: str, user_text: str) -> None:
        if not user_text:
            await self._reply(cid, "Напиши: /chat <сообщение>.")
            return
        async with _CHAT_LOCK:
            await db.add_turn("user", user_text)
            system, history, user = await llm_context.build_messages(user_text)
            reply = await llm.generate(system, user, history)
            if reply:
                await db.add_turn("assistant", reply)
                await self._reply(cid, reply)
            else:
                await self._reply(cid, messages.llm_offline_text())

    # ------------------------------ колбэки ------------------------------- #
    async def _on_callback(self, cb: dict) -> None:
        cid = cb.get("callback_id")
        data = cb.get("payload") or cb.get("callback_data") or ""
        user_id = _msg_user_id(cb)
        msg = cb.get("message") or {}
        chat_id = _extract_chat_id(msg) or self.owner_chat_id
        if not await self._learn_owner(chat_id, user_id):
            return

        async def notify(t: str) -> None:
            await self._answer_cb(cid, notification=t)

        if data == "morning:done":
            today = planner.today_iso(_tz())
            st = await db.get_state()
            await db.upsert_log(today, st["current_day"], morning_done=True)
            await self._answer_cb(cid, notification="Утренний запуск засчитан 🔥", message={"attachments": []})
            await settle(today, "morning", "max")
        elif data == "morning:later":
            await self._answer_cb(cid, notification="Окей, без давления 🌿", message={"attachments": []})
            await settle(planner.today_iso(_tz()), "morning", "max")
        elif data == "ping:done":
            await self._answer_cb(cid, notification="👍 Красава", message={"attachments": []})
            await settle(planner.today_iso(_tz()), "ping", "max")
        elif data == "ping:skip":
            await self._answer_cb(cid, notification="Без проблем 🙂", message={"attachments": []})
            await settle(planner.today_iso(_tz()), "ping", "max")
        elif data == "theory:done":
            await self._answer_cb(cid, notification="Прочитано 📖", message={"attachments": []})
        elif data == "hard":
            extra = 2
            await db.update_state(week_extra_days=extra)
            await self._send_to(chat_id, messages.hard_confirm_text(extra))
            await self._answer_cb(cid, notification="Задерживаемся 🌿", message={"attachments": []})
        elif data.startswith("pl:"):
            raw = data.split(":", 1)[1]
            if not (raw.isdigit() and 0 <= int(raw) <= 3):
                await notify(""); return
            day = (await db.get_state())["current_day"]
            await db.upsert_log(planner.today_iso(_tz()), day, pain=int(raw))
            text, kb = messages.locations_prompt()
            await self._answer_cb(cid, notification="", message=_cb_message(text, kb))
        elif data.startswith("loc:"):
            loc = data.split(":", 1)[1] if ":" in data else ""
            if loc not in messages._LOCATIONS:
                await notify(""); return
            day = (await db.get_state())["current_day"]
            await db.upsert_log(planner.today_iso(_tz()), day, note=loc)
            text, kb = messages.habits_prompt()
            await self._answer_cb(cid, notification="", message=_cb_message(text, kb))
        elif data.startswith("habits:"):
            await self._handle_habits(data, chat_id, cid, cb)

    async def _handle_habits(self, data: str, chat_id: str, callback_id, cb: dict) -> None:
        """Финал вечернего опроса: привычки → фидбек + стрик (зеркало cb_habits)."""
        code = data.split(":", 1)[1] if ":" in data else ""
        if code not in ("yes", "partial", "no"):
            await self._answer_cb(callback_id, notification="")
            return
        habits_done = code in ("yes", "partial")
        tz = _tz()
        today = planner.today_iso(tz)
        state = await db.get_state()
        day = state["current_day"]
        today_log = await db.get_log(today) or {}
        pain_level = today_log.get("pain")
        location = today_log.get("note")
        await db.upsert_log(today, day, habits_done=habits_done, evening_done=True)
        new_streak, changed = await planner.update_streak(state, tz)
        if changed:
            await db.update_state(streak=new_streak, last_log_date=today)
        if pain_level is None:
            await self._answer_cb(callback_id, notification="",
                                  message=_cb_message("Засчитал вечер ✅ Завтра снова соберём метрики.", None))
        else:
            text, kb = messages.feedback_text(day, pain_level, location, new_streak)
            await self._answer_cb(callback_id, notification="", message=_cb_message(text, kb))


def _cb_message(text: str, tg_kb: InlineKeyboardMarkup | None) -> dict:
    """Тело для обновления сообщения в POST /answers (ответ на колбэк)."""
    msg: dict = {"text": text[:4000], "format": "markdown"}
    att = kb_to_max(tg_kb)
    if att:
        msg["attachments"] = att
    return msg


def _parse_rating(data: str, prefix: str) -> int | None:
    if not data.startswith(f"{prefix}:"):
        return None
    raw = data.split(":", 1)[1]
    if not raw.isdigit():
        return None
    v = int(raw)
    return v if 1 <= v <= 10 else None


def _tz() -> str:
    from config import config
    return config.schedule.timezone
