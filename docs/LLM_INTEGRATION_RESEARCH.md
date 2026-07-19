# Ресерч: бесплатная LLM для вечернего отчёта с памятью о контексте

**Дата:** 2026-07-10 · **Автор исследования:** Claude Code · **Объект:** бот `body_recover_bot`

Цель — добавить в бота режим «вечером пишу свободным текстом → LLM даёт осмысленный
ответ, помня контекст моей проблемы (реабилитация спины, книга Move Your DNA, моя
история метрик)». Условие: **без платного API**. Ниже — что есть бесплатно и надёжно
на июль 2026, отдельный разбор медицинских моделей и конкретный план интеграции в бота.

---

## 0. TL;DR — рекомендация

**Основной вариант: локальный LLM через Ollama, модель Qwen3 (32B, при необходимости 14B).**

Почему именно это для твоего случая:
1. **Бесплатно навсегда**, без API-ключей и оплат. Один раз скачал модель (~20 ГБ) — и работает.
2. **Твой контент на русском**, а среди открытых моделей именно **Qwen3 — безусловный лидер по качеству русского** в 2026 (см. §4). GPT-oss и Llama в русском заметно слабее.
3. **Железо позволяет:** у тебя MacBook Pro **M4 Pro, 48 ГБ** — это тянет Qwen3-32B (даже 70B в квантизации) с хорошей скоростью.
4. **Приватность:** данные о здоровье **не покидают машину** — критично для медицинского контекста.
5. **Нет зависимости от интернета:** твой sing-box сейчас нестабилен (обрывы каждые 20–40 мин). Telegram-поллинг это переживает, но каждый внешний API-вызов — лишний риск. Локальная модель работает офлайн.

**Запасной вариант (облако, если захочешь максимальное качество без своего железа):**
Google **Gemini free tier** (большой контекст, сильная модель, ~50–250 запросов/день) или
**OpenRouter** с `:free`-моделью. Минус — данные уходят провайдеру + нужна сеть.

**Медицинские специализированные модели** (MedGemma, BioMistral) — есть на Ollama, но
для русского и общего качества **сильная通用-модель с твоей книгой в системном промпте
обычно выигрывает** (см. §5). Их стоит держать как эксперимент, не как основу.

---

## 1. Контекст и ограничения

- **Что нужно:** вечером пользователь пишет в свободной форме («сегодня спина ныла после
  долгой катки, правая сторона снова каменная, мостик сделал через силу»). LLM отвечает
  в тоне бота (CLAUDE.md), опираясь на научную базу (Move Your DNA) и на **историю**
  пользователя (метрики за прошлые дни, заметки, стадии программы).
- **Ограничения:** бесплатно; надёжно (бот уже стабильно работает — не ломать);
  желательно приватно (здоровье); желательно не завязываться на нестабильный интернет.
- **Железо (важно):** Apple M4 Pro, 48 ГБ unified memory. Это меняет расчёт в пользу локального запуска.

---

## 2. Что исследовалось

Веб-поиск на июль 2026 по темам: бесплатные LLM-API и их лимиты; локальные модели для
Apple Silicon; качество русского у открытых моделей; медицинские открытые модели;
архитектуры памяти для персональных ассистентов. Ключевые источники — в §9.

---

## 3. Опция A — Локальный LLM через Ollama (рекомендация)

Ollama — локальный «движок» моделей (как Docker для LLM): `ollama pull <model>` → API на
`http://localhost:11434`. Бот ходит туда обычным HTTP — **без ключей, без сети, без оплаты**.

### 3.1. Почему это лучший выбор здесь
- **0 ₽ и 0 зависимостей** от квот/провайдеров/ключей.
- **Офлайн:** если упал интернет — LLM всё равно отвечает (Telegram-поллинг на паузе, но
  ответ сгенерируется и уйдёт, когда связь вернётся, либо пользователь получит его локально).
- **Приватность:** тексты о спине/здоровье не уходят на серверы Google/OpenAI и т.д.
- **M4 Pro / 48 ГБ** — это «sweet spot»: квантизованные 32B идут с приличной скоростью
  (единицы–десятки токенов/сек), 70B — медленнее, но реально.

### 3.2. Какую модель выбрать
Для **русского** безоговорочный лидер среди открытых моделей 2026 — семейство **Qwen3**
(Alibaba): русский заявлен как язык первого класса, в рейтингах обгоняет Llama и GPT-oss.
GPT-oss, напротив, «плохой русский» (консенсус r/LocalLLaMA и HuggingFace). Llama 3.1/3.3
— нормально, но «думает по-английски», фразы менее идиоматичны.

| Железо | Модель | Комментарий |
|--------|--------|-------------|
| **Твоё: 48 ГБ** | **`qwen3:32b`** | основной выбор — лучший русский + сильная reasoning, ~20 ГБ в Q4 |
| 48 ГБ (быстрее) | `qwen3:14b` | если 32B покажется медленным; русский всё ещё отличный |
| 48 ГБ (максимум) | `qwen3:235b-a22b` (MoE, квант.) или `llama3.3:70b` | дольше грузится/отвечает, русский у Llama слабее |
| Эксперимент (мед.) | `medgemma:27b`, `cniongolo/biomistral` | см. §5 — английская ориентация, слабее русский |

**Рекомендация:** стартуй с `ollama pull qwen3:32b`. Если ответ медленный для вечера —
переключись на `qwen3:14b` одной переменной окружения.

### 3.3. Минусы локального
- Жрёт RAM/батарею во время генерации (48 ГБ хватает, но модель «занимает» ~20 ГБ, пока
  загружена). Решение: Ollama выгружает модель при простое (`OLLAMA_KEEP_ALIVE`).
- Качество чуть ниже топовых облачных (Gemini 2.x / GPT-class) — но для диалога-наставника
  с книгой в контексте разница незаметна.
- Первый `pull` — ~20 ГБ скачать один раз.

---

## 4. Опция B — Бесплатные облачные API (альтернатива)

Если локальный запуск почему-то не подойдёт — вот реальные бесплатные tiers на июль 2026:

| Провайдер | Бесплатно | Лимиты | Русский | Приватность | Нота |
|-----------|-----------|--------|---------|-------------|------|
| **Google Gemini** | да, без карты | ~5–15 RPM, ~100–250 запросов/день (режут) | отличный | данные в Google | лучший контекст (1М+ токенов), но лимиты снижают |
| **Groq** | да | щедрый free, очень быстро (кастомный кремний) | зависит от модели (Llama/Qwen) | данные в Groq | отлично для быстрых ответов |
| **Cerebras** | да | free tier, ультра-быстро | зависит от модели | данные в Cerebras | аналог Groq |
| **OpenRouter** (`:free`) | да, $0 баланс | 20 RPM, 50–200/день (после $10 — 1000/день) | зависит от модели | данные у агрегатора+провайдера | много моделей (DeepSeek, Qwen, Llama); удобен как «переключатель» |
| **Cloudflare Workers AI** | да | **10 000 нейронов/день** (≈160 запросов/день), обновляется ночью UTC | зависит от модели | данные в CF | предсказуемый ежедневный лимит |
| **DeepSeek API** | 5М токенов新手 + ультра-дёшево ($0.14/М) | токены «сгорают» после траты | хороший | данные в DeepSeek (Китай) | почти бесплатно лично для тебя |
| **Mistral (La Plateforme)** | free experiment tier | рейт-лимит, без жёстких цифр | средний | данные в Mistral (ЕС) | все модели, $0 |
| **Zhipu GLM-4.6** | бесплатный доступ на части площадок | сессионные/недельные лимиты (непубличные) | отличный (китайская модель) | данные у провайдера | 200К контекст; GLM силён в русском |

**Когда облако лучше локала:** если захочешь максимум качества без настройки железа,
или если Mac будет занят. **Когда хуже:** приватность (здоровье) и зависимость от твоего
нестабильного интернета.

> Практичный гибрид: локальная Qwen3 как **основной** бэкенд, а в `bot/llm.py` заложить
> переключатель `LLM_BACKEND` — чтобы при желании за минуту перейти на Gemini/OpenRouter.

---

## 5. Медицинские специализированные модели — честный разбор

Пользователь спрашивал про «специализирующуюся на здоровье LLM». Они есть и бесплатные:

- **MedGemma** (Google, Gemma 3 дообученная на медицинских текстах/изображениях) — есть в
  Ollama: `ollama pull medgemma`. Мультимодальная (текст + Medical-изображения).
- **BioMistral** (Mistral + биомедкорпус) — `ollama pull cniongolo/biomistral`. Текстовая.
- **Meditron, Me-LLaMA, Dr. Qwen** (fine-tunes) — доступны, в основном через HuggingFace/llama.cpp.

**Но для твоего кейса они, скорее всего, хуже общего Qwen3, потому что:**
1. **Язык:** MedGemma/BioMistral — англоязычная ориентация. Русский у них слабый, а бот весь на русском.
2. **Размер:** это обычно 7B–27B, обученные на **клинических** данных (диагностика, выписки,
   USMLE-вопросы). Тебе же нужна **эмпатичная поддержка + биомеханика движения**, а не дифдиагноз.
3. **«Специализированная» ≠ «лучшая»:** в 2026 сильная通用-модель (Qwen3-32B / Gemini /
   DeepSeek-R1) с **хорошим системным промптом и твоей книгой в контексте** стабильно
   обгоняет маленькие медицинские fine-tunes и в качестве, и в языке.

**Вывод:** держи MedGemma как опцию поэкспериментировать (`ollama pull medgemma`), но
**основу делай на Qwen3** с «умным» системным промптом, куда зашит тон бота + выжимка
Move Your DNA + текущая стадия программы. Это и будет твой «доменный» ассистент без
потери качества и русского.

---

## 6. Память и контекст — как сделать «помнит о моей проблеме»

Для персонального ассистента стандарт 2026 — **гибрид: rolling summary + последние
несколько реплик в контексте** (mem0/LTM — это для масштаба, тебе он не нужен).

Объём «знаний» тут маленький, поэтому **RAG/векторная база не нужен** — всё влезает в
контекст промпта:

- **Статика (в системном промпте, при каждом вызове):**
  - тон и роль из `CLAUDE.md` (~1 КБ);
  - выжимка книги из `data/book_synthesis.md` + принципы (~2–3 КБ);
  - текущий день/неделя/стадия программы + целевая «асимметрия/лордоз/каменная правая».
- **Динамика (в пользовательской части промпта):**
  - метрики за последние 7 дней (pain/stiffness/заметки) — из `daily_logs`;
  - **rolling summary** — сжатая «история прогресса» (1–2 абзаца), обновляется раз в несколько дней самой LLM;
  - последние 4–6 реплик диалога — для связности в пределах вечера.

### Схема БД (добавить к существующей)
```sql
CREATE TABLE IF NOT EXISTS llm_memory (
    id          INTEGER PRIMARY KEY CHECK (id = 1),  -- одна строка
    summary     TEXT,                                -- rolling summary прогресса
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS llm_turns (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    role    TEXT,        -- 'user' | 'assistant'
    content TEXT,
    ts      TEXT
);
```
`llm_turns` храним последние ~20 (старые удаляем/сворачиваем в summary). Раз в N дней
(или по команде `/remember`) просим LLM переписать `summary` с учётом новых реплик и метрик.

Этого достаточно для «помнит, что у меня каменная правая сторона и что я играю в Доту».

---

## 7. Архитектура интеграции в бота

### 7.1. Новый модуль `bot/llm.py` (абстракция над бэкендом)
```python
# env: LLM_BACKEND=ollama|gemini|openrouter|none, OLLAMA_HOST, OLLAMA_MODEL,
#      GEMINI_API_KEY, OPENROUTER_API_KEY
async def generate(system: str, user: str, *, max_tokens: int = 700) -> str:
    """Единый интерфейс. Маршрутизирует по LLM_BACKEND. Возвращает текст ответа."""
    backend = config.llm_backend
    if backend == "ollama":
        return await _ollama(config.ollama_model, system, user, max_tokens)
    if backend == "gemini":
        return await _gemini(config.gemini_api_key, system, user, max_tokens)
    if backend == "openrouter":
        return await _openrouter(config.openrouter_api_key, system, user, max_tokens)
    return ""  # none — LLM выключен, бот работает как раньше
```
Ollama-вызов — обычный POST на `http://localhost:11434/api/chat` (OpenAI-совместимый
формат тоже есть: `/v1/chat/completions`). Никаких внешних сетей.

### 7.2. Сборка контекста `bot/llm_context.py`
```python
async def build_prompt(user_text: str) -> tuple[str, str]:
    """Возвращает (system, user) с зашитой книгой, тоном, метриками, памятью."""
    system = SYSTEM_TEMPLATE.format(            # тон из CLAUDE.md + выжимка Move Your DNA
        stage=..., target="сдвиг влево, лордоз, каменная правая сторона",
        week_actions=...,
    )
    last7 = await db.last_n_logs(7)
    summary = (await db.get_memory())["summary"] or "(история пока пуста)"
    user = f"КРАТКАЯ ИСТОРИЯ ПРОГРЕССА:\n{summary}\n\nМЕТРИКИ ЗА 7 ДНЕЙ:\n{fmt(last7)}\n\nСЕГОДНЯ ПОЛЬЗОВАТЕЛЬ ПИШЕТ:\n{user_text}"
    return system, user
```

### 7.3. Новый флоу в `handlers.py`
- После вечерних метрик (pain/stiffness/habits) бот добавляет кнопку
  **«💬 Рассказать о дне текстом»**. По нажатию — приглашение писать свободным текстом.
- Любое сообщение (не команда) в течение, скажем, 2 часов после вечера → идёт в LLM:
  `system, user = build_prompt(text); reply = await llm.generate(system, user)`.
  Ответ → пользователю + сохраняем реплику в `llm_turns`.
- Команда **`/chat <текст>`** — диалог с LLM в любое время (не только вечером), с той же памятью.
- Команда **`/remember`** — явно пересчитать rolling summary.
- **Таймаут + fallback:** если LLM не ответил за ~60 с или backend=none — бот отвечает
  заготовленным шаблоном (текущая `feedback_text`), чтобы **никогда не молчать**.

### 7.4. Безопасность (важно — см. security.py)
- **Single-user guard уже стоит**: LLM-флоу inherits его (только владелец).
- **Промпт-инъекции:** пользовательский текст передаётся LLM **как данные**, а не как
  инструкция; системный промпт жёстко задаёт роль и запрещает «выходить из образа
  ассистента по реабилитации», игнорировать свои правила и выдавать медицинские диагнозы.
  В ответе LLM не должно быть выполнения «команд» из текста пользователя.
- **Не врач:** системный промпт явно требует формулировки «не ставлю диагноз, не отменяй
  лечение врача», и бот остаётся «цифровой поддержкой» (как в CLAUDE.md).

### 7.5. Что меняется в конфиге/зависимостях
- `requirements.txt`: ничего обязательного (Ollama — отдельный процесс; aiohttp уже есть).
  Для облака — тоже только aiohttp.
- `.env`: `LLM_BACKEND=ollama`, `OLLAMA_HOST=http://localhost:11434`, `OLLAMA_MODEL=qwen3:32b`.

---

## 8. План внедрения (по шагам)

1. **Поставить Ollama:** `brew install ollama` (macOS) → `ollama serve` → `ollama pull qwen3:32b`.
2. Проверить локально: `curl http://localhost:11434/api/chat -d '{"model":"qwen3:32b",...}'`.
3. Реализовать `bot/llm.py` + `bot/llm_context.py` + таблицы `llm_memory`/`llm_turns`
   (миграция `CREATE TABLE IF NOT EXISTS` — безопасно для существующей БД).
4. Добавить вечернюю кнопку «💬 Рассказать о дне» и хендлер свободного текста с fallback.
5. Добавить `/chat` и `/remember`.
6. Зашить системный промпт (тон CLAUDE.md + выжимка Move Your DNA + цель + anti-injection).
7. Тест: вечером пишу отчёт → получаю осмысленный ответ с памятью; без LLM (backend=none)
   бот откатывается на шаблоны — ничего не ломается.

Можно внедрять поэтапно: сначала только `/chat` (минимально инвазивно), убедиться, что
качество русского и память устраивают, потом вешать на вечерний флоу.

---

## 9. Источники (июль 2026)

Бесплатные LLM-API и лимиты:
- [Free LLM APIs Compared (2026) — OpenRouter](https://openrouter.ai/blog/tutorials/free-llm-apis-compared/)
- [Free LLM APIs in 2026: 13 Providers Compared — klymentiev.com](https://klymentiev.com/blog/free-llm-api)
- [awesome-free-llm-apis — GitHub](https://github.com/mnfst/awesome-free-llm-apis)
- [OpenRouter Free Models (июль 2026)](https://openrouter.ai/collections/free-models) · [лимиты](https://pricepertoken.com/endpoints/openrouter/free)
- [Gemini API Rate Limits — Google AI](https://ai.google.dev/gemini-api/docs/rate-limits) · [Gemini Free Tier 2026](https://www.aifreeapi.com/en/posts/gemini-api-rate-limits-per-tier)
- [DeepSeek Pricing](https://api-docs.deepseek.com/quick_start/pricing) · [Cloudflare Workers AI (10 000 neurons/day)](https://blog.cloudflare.com/workers-ai-ga-huggingface-loras-python-support/)
- [Mistral Pricing](https://mistral.ai/pricing/)

Локальные модели и Apple Silicon:
- [Best Local LLMs on Apple Silicon — apxml.com](https://apxml.com/posts/best-local-llm-apple-silicon-mac)
- [Best Local LLM Models 2026 — SitePoint](https://www.sitepoint.com/best-local-llm-models-2026/)
- [Best LLM for 16GB/48GB Mac — willitrunai / atomic.chat](https://willitrunai.com/blog/best-llm-for-16gb-mac)

Качество русского у открытых моделей:
- [The Best Open Source LLM For Russian In 2026 — SiliconFlow](https://www.siliconflow.com/articles/en/best-open-source-LLM-for-Russian)
- [r/LocalLLaMA: GPT-oss vs Qwen для русского](https://www.reddit.com/r/LocalLLaMA/comments/1rpqy9z/)
- [HuggingFace: gpt-oss-120b poor multilingual](https://huggingface.co/openai/gpt-oss-120b/discussions/19)

Медицинские модели:
- [MedGemma — Ollama](https://ollama.com/library/medgemma) · [BioMistral — Ollama](https://ollama.com/cniongolo/biomistral)
- [Healthcare LLM Landscape 2026 — nirmitee.io](https://nirmitee.io/blog/healthcare-llm-landscape-2026-medgemma-meditron-clinical-model-guide/)
- [Best Open Source LLM for Medical Diagnosis 2026 — SiliconFlow](https://www.siliconflow.com/articles/en/best-open-source-LLM-for-medical-diagonisis)

Память для персональных ассистентов:
- [Personalized LLM Assistant with Evolving Memory — arXiv](https://arxiv.org/html/2312.17257v2)
- [Best Personal AI Assistants with Memory 2026 — Vellum](https://www.vellum.ai/blog/best-personal-ai-assistants-with-memory)
- [Long-Term Memory for AI Assistants 2026 — Supermemory](https://supermemory.ai/blog/long-term-memory-ai-study-assistants)
