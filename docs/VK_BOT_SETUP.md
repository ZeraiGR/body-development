# Создание бота в VK и подключение второго (приватного) канала

VK (ВКонтакте) — второй канал доставки курса вместо Telegram/Max. Выбран, потому что:
работает в РФ **без VPN**, **бесплатно**, **без бизнес-верификации** (нужна только группа +
токен), **Long Poll API не требует домена/HTTPS** (бот сам опрашивает VK с VPS).

> Главное требование — **приватная переписка** (не общедоступная). Как это обеспечено — ниже.

---

## Приватность: почему это личный канал

1. **Сообщения сообщества — это диалог 1-на-1.** Ты пишешь сообществу, оно отвечает. Переписку
   видят **только ты и админы сообщества** (админ — ты сам). Другие пользователи VK её **не видят**;
   это НЕ публичный чат и НЕ стена.
2. **Сообщество «Закрытое» + убрано из поиска** → его никто не находит, оно существует лишь как
   «оболочка» для личных сообщений.
3. **Whitelist по `user_id`** — бот отвечает **только твоему** VK ID. Любые чужие сообщения
   игнорируются (как уже сделано в текущем TG-боте через `security.AuthMiddleware`).

---

## Шаги (≈5 минут, бесплатно)

1. В VK **создать сообщество** (группа). При создании / в «Управление → Информация»:
   - Тип → **«Закрытая»** (видна только участникам).
   - «Управление → Разделы/Поиск» → **убрать сообщество из поиска** (запретить индексацию).
2. «Управление → **Сообщения**» → включить **«Сообщения сообщества»**.
3. «Управление → **Работа с API → Ключи доступа**» → создать токен с правами
   `messages`, `groups`, `offline` → скопировать.

`vk1.a.rzoV64W9HaXxT53U3ao_w4VwpoTYF2y07aMCgXfcBpTDDuaTfXmae9uTJLCfJVlv2t1PY96jVEQF0kM2JIpKIFKbOwyOjIOYggvtUerGBnGRs5S1sv_enX5Yb5PT-H-y7hZLdQjq1FupS8DEEwkwjtAdAwKhXL1o8mfSWSTCUy0X7slxL6aqlpEBIaWQF7lxJ7vYnZqrbHwpcARSVvInmw`

4. Там же → «**Long Poll API**» → **включить** (актуальная версия). Это режим без webhook'а —
   домен НЕ нужен, бот сам опрашивает VK.
5. Узнать свой **VK `user_id`** (числовой) — например из URL профиля или сервиса вроде
   `regvk.com`. Это ID для whitelist'а бота - `206965034`

6. Положить в `/root/body-development/.env` на VPS:
   ```bash
   ssh root@194.62.66.34
   nano /root/body-development/.env
   # добавить:
   #   VK_TOKEN=<токен>
   #   VK_USER_ID=<твой числовой VK id>
   # Ctrl+O, Enter, Ctrl+X
   systemctl restart back-bot
   ```
   Токен — секрет, **не коммитить и не пересылать в чат**.
7. Написать сообществу любое сообщение → бот стартует диалог (приватно, только тебе).

---

## Техническая справка по VK Bot API (для сборки)

| Параметр | Значение |
|---|---|
| Получение событий | **Bots Long Poll API** (опрашивает бот; без домена) или Callback API (webhook, нужен HTTPS) |
| Авторизация | `access_token` в параметрах запросов |
| Отправка ЛС | `messages.send` с `peer_id` = `user_id` (ЛС от сообщества пользователю) |
| Клавиатура | параметр `keyboard` (JSON): кнопки `text`, `link`, `callback`; `inline=True` для inline |
| Колбэк кнопки | событие `message_event` (VK > API 5.103) → `messages.sendMessageEventAnswer` |
| Редактирование сообщений | `messages.edit` (текст/клавиатура) |
| Форматирование | VK не парсит TG-Markdown → бот снимает `**`/`*`/`_`/`` ` `` маркеры (`_strip_md`), текст идёт plain. Эмодзи и структура сохраняются |
| Rate limit | ~20 запросов/сек к `messages.send` (для одного пользователя некритично) |
| Python SDK | **без SDK** — минимальный клиент на `aiohttp` (`bot/vk_bot.py`): Long Poll + `messages.send`/`edit`/`sendMessageEventAnswer`. `aiohttp` уже есть через aiogram, ставить ничего не надо. `group_id` для Long Poll определяется автоматически через `groups.getById` (отдельный `VK_GROUP_ID` не нужен) |

### Приватность в коде
- `AuthMiddleware`/whitelist: бот принимает события только от `VK_USER_ID`; чужие — `ignore`.
- Сообщество закрыто и скрыто из поиска — внешних запросов практически не будет.

---

## Реализация (статус)

**Сделано** (`bot/vk_bot.py`, запускается в одном процессе с TG через `main.py`):
- Long Poll Bots API (aiohttp), автоопределение `group_id`.
- Whitelist по `VK_USER_ID` — чужие сообщения/клики игнорируются (приватный канал).
- Команды: `/start /help /status /today /theory N /evening /ping /report /pause /resume /next /hard /reset /chat /remember` — зеркало `handlers.py`.
- Колбэки-кнопки (та же `callback_data`, что в TG): утро/пинг/теория done, боль→жёсткость→привычки→фидбек (вечерняя машина состояний), «тяжело → задержаться».
- Конвертер клавиатур TG→VK (`kb_to_vk`): callback- и link-кнопки.
- Scheduler (`scheduler.py._send`) дублирует утро/пинг/вечер/отчёт/VPS-напоминание в VK (best-effort, не ломает идемпотентность TG).
- Markdown снимается до plain (VK не парсит `*`/`_`).

**Не сделано (задача #5, позже):** фоллбек TG→VK (2ч), `/channel telegram|vk|auto` (выбор канала), `msg_refs`-синхронизация кнопок между платформами. Сейчас рассылки идут в ОБА мессенджера одновременно.

---

## Источники

- [VK Bots Long Poll API](https://vk.com/dev/bots_longpoll), [VK API methods](https://dev.vk.com/method/messages)
- [vkbottle (async Python SDK)](https://github.com/vkbottle/vkbottle), [документация vkbottle](https://vkbottle.readthedocs.io)
- [Создание бота ВК (Habr)](https://habr.com/ru/articles/428680/), [Timeweb: бот ВК](https://timeweb.com/ru/community/articles/kak-sozdat-bota-dlya-viber-1)
