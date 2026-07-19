# Управление ботом через VPS — шпаргалка

Архитектура (итог миграции 2026-07-10):

```
┌─────────────────────────── VPS 194.62.66.34 (Ubuntu 24.04) ───────────────────────────┐
│  back-bot.service (systemd)  ← бот 24/7: утро/пинг/вечер/VPS-напоминание/sweep          │
│  data/bot.db                ← весь прогресс (день/метрики/статьи/память), бэкап 04:30   │
│  Telegram — напрямую (без прокси, DC-канал)                                             │
│  Tailscale-узел: 100.85.223.71 (armed-rose)                                             │
└───────────────▲──────────────────────────────── Tailscale ──────────────────────────────┘
                │ ИИ-запросы (http://100.72.19.121:11434)
┌───────────────┴─────────────────────── Mac (M4 Pro) ───────────────────────────────────┐
│  Ollama + qwen3:32b  ← LaunchAgent local.ollama, привязан к Tailscale-IP                │
│  Tailscale-узел: 100.72.19.121 (msk-...)                                                │
│  sing-box (SOCKS5 :1080)  ← локальный прокси для TG/YouTube пользователя (не бота)      │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

Главное: **ядро бота живёт на VPS и не зависит от Mac. ИИ работает, когда Mac включён** (иначе бот откатывается на шаблоны — не молчит).

---

## 1. Подключение к VPS

На Mac уже настроен **беспарольный SSH по ключу**:
```bash
ssh root@194.62.66.34
```
(Ключ `~/.ssh/id_ed25519`.) **Вход по паролю отключён** (`PasswordAuthentication no` с 2026-07-11) — SSH работает только по ключу. Root-пароль ротейтнут и лежит в macOS Keychain (см. «Секреты»), нужен только для консоли хостинга в крайнем случае.

Каталог бота на VPS: `/root/body-development`.

## 2. Бот: статус / перезапуск / логи

> **Второй канал (MAX):** подключение бота в мессенджере MAX (фоллбек TG→MAX, `/channel`, `/theory N`) — в `docs/MAX_BOT_SETUP.md`. Токен кладётся в `MAX_BOT_TOKEN` в `.env` на VPS.

```bash
systemctl status back-bot        # состояние + последние строки
systemctl restart back-bot       # перезапуск (подхватит новый код/.env)
systemctl stop back-bot          # стоп
systemctl start back-bot         # старт
journalctl -u back-bot -f        # логи вживую (Ctrl+C — выход)
journalctl -u back-bot -n 50     # последние 50 строк
journalctl -u back-bot --since "1 hour ago"
```
При `Restart=always` бот сам поднимется после падения или рестарта VPS.

## 3. Обновить код бота (с Mac на VPS)

После правок кода на Mac — синхронизируй и перезапусти:
```bash
cd ~/work/body-development
rsync -az --delete \
  --exclude='.venv/' --exclude='__pycache__/' --exclude='*.pyc' \
  --exclude='.env' --exclude='.env.*' \
  --exclude='*.pdf' --exclude='data/' \
  --exclude='.git/' \
  -e ssh ./ root@194.62.66.34:~/body-development/
ssh root@194.62.66.34 'systemctl restart back-bot'
```
⚠️ **Никогда не синхронизируй `.env` и `data/` с Mac на VPS.** `.env` на VPS — источник правды (там `BOT_TOKEN`, `VK_TOKEN` и т.п., которые ты вписывал вручную); локальный `.env` их не содержит, и rsync перезапишет/затрёт секреты. `data/` содержит продакшн `bot.db` (прогресс) и статьи — rsync затрёт прогресс версией с Mac. Поэтому `.env` и `data/` всегда в `--exclude`. Меняешь только код → rsync → restart.

## 4. Поменять настройки (.env) на VPS

```bash
ssh root@194.62.66.34
nano /root/body-development/.env      # правим (время рассылок, LLM, VPS-данные и т.д.)
systemctl restart back-bot
```
Ключевые переменные уже выставлены: `LLM_BACKEND=ollama`, `OLLAMA_HOST=http://100.72.19.121:11434`, `TG_PROXY=` (пусто — прямой интернет), `BOT_TOKEN`, `ALLOWED_CHAT_ID`, `TELEGRAPH_TOKEN`.

## 5. База прогресса и бэкапы

- Файл: `/root/body-development/data/bot.db` (SQLite). В нём **всё**: день/стрик, метрики, ссылки статей, sent_log, память LLM.
- Бэкап: cron-root ежедневно в **04:30** → `/root/body-development/data/backups/bot-ГГГГММДД.db`, хранение 14 дней.
- Снять свежую копию на Mac (например, перед правками): 
  ```bash
  scp root@194.62.66.34:/root/body-development/data/bot.db ~/bot-backup-$(date +%F).db
  ```

## 6. ИИ: Ollama на Mac

Ollama крутится как **LaunchAgent `local.ollama`** (автозапуск при входе, KeepAlive), привязан к Tailscale-IP `100.72.19.121:11434`.
```bash
launchctl list | grep local.ollama                 # работает? (PID и статус 0)
curl http://100.72.19.121:11434/api/version        # отвечает?
ollama list                                        # модель qwen3:32b на месте?
lsof -nP -iTCP:11434 -sTCP:LISTEN                  # слушает 100.72.19.121:11434?
```
Перезапуск Ollama:
```bash
launchctl unload ~/Library/LaunchAgents/local.ollama.plist
launchctl load   ~/Library/LaunchAgents/local.ollama.plist
```
Если **Mac уснул/выключен** — VPS-бот не достучится до Ollama → `/chat` ответит заглушкой «ИИ не на связи». Ядро бота (рассылки) при этом работает на VPS как ни в чём не бывало.

## 7. Tailscale (связка VPS ↔ Mac)

```bash
tailscale status                  # оба узла online? их IP
tailscale ip -4                   # IP этого узла
```
- Mac: `100.72.19.121`, VPS: `100.85.223.71`. IP стабильные.
- Сервисы автозапускаются: Mac — `sudo brew services start tailscale`, VPS — `tailscaled` (systemd).

## 8. VPN: ShadowTLS v3 (DPI-устойчивый) — Mac SOCKS5 + телефон

**Почему не Reality.** VLESS+Reality (порт 443, контейнер `amnezia-xray`) на провайдере пользователя (AS42610, Москва) **блокируется DPI** — handshake Reality детектится независимо от SNI (проверено: смена SNI на bing.com не помогла, телефон тоже не коннектится). Сервер Reality на VPS оставлен (работает из других сетей), но с этого ISP бесполезен. Вместо него поднят **ShadowTLS v3 + Shadowsocks 2022** на порту **8443** — трафик маскируется под обычный TLS к `www.bing.com`, DPI его не отличает от реального HTTPS.

**Архитектура (Mac):** sing-box крутится как **локальный SOCKS5-прокси** на `127.0.0.1:1080` (**без tun-интерфейса, без root**) → трафик уходит через ShadowTLS на VPS. Это **сосуществует с Tunnelblick** (рабочий VPN на весь день): Tunnelblick владеет своим tun, а sing-box только делает исходящие TCP к `194.62.66.34:8443` и слушает localhost — конфликта нет. Telegram-десктоп и браузер настраиваются на SOCKS5 `127.0.0.1:1080`.

Сервер на VPS: systemd-юнит `sing-box-st` (`/etc/sing-box-st/config.json`, бинарий `/usr/local/bin/sing-box` 1.13.14). Секреты — `/etc/sing-box-st/secrets` (chmod 600).

Параметры сервера ShadowTLS (одинаковые для всех клиентов):

| Параметр | Значение |
|---|---|
| Протокол | ShadowTLS v3 + Shadowsocks 2022-blake3-aes-128-gcm |
| Адрес | `194.62.66.34:8443` |
| ShadowTLS-пароль | `<ST_PW — на VPS: /etc/sing-box-st/secrets>` |
| SS-2022 ключ | `<SS_KEY — там же>` |
| SNI (камуфляж) | `www.bing.com` |
| uTLS fingerprint | `chrome` |

### 8.1 Mac: SOCKS5-прокси (sing-box, без root)

sing-box запущен как **пользовательский LaunchAgent `local.singbox-st`** (автозапуск при входе, KeepAlive, **без sudo**). Конфиг: `~/.singbox-st.json` (`/Users/kagruzdev/.singbox-st.json`). Внутри: `mixed`-inbound на `127.0.0.1:1080`, `shadowsocks`-outbound с `detour`→`shadowtls`-outbound (server `194.62.66.34:8443`), DNS через прокси (`1.1.1.1`), `route.final=ss-out`.

```bash
# статус агента / процесса
launchctl list | grep local.singbox-st
pgrep -fl singbox-st.json
curl -s --socks5-hostname 127.0.0.1:1080 --max-time 15 https://api.ipify.org   # должно вернуть 194.62.66.34

# перезапуск агента (без sudo)
launchctl unload ~/Library/LaunchAgents/local.singbox-st.plist
launchctl load   ~/Library/LaunchAgents/local.singbox-st.plist
tail -f /tmp/sb-st.log                # лог

# валидация конфига после правки
sing-box check -c ~/.singbox-st.json
```

**Старый tun-демон (Reality) нужно выключить** — раньше был root-демон `/Library/LaunchDaemons/local.singbox.plist` (tun+Reality, мёртвый из-за DPI, плюс перехватывал TG/YouTube и ломал их). Выгрузить (нужен `sudo`, в Terminal — не через `!`):
```bash
sudo launchctl bootout system/local.singbox 2>/dev/null
sudo mv /Library/LaunchDaemons/local.singbox.plist /Library/LaunchDaemons/local.singbox.plist.disabled
```
Если `bootout` ругается «not found» — значит уже выгружен, достаточно `mv`. Старый конфиг `~/.singbox.json` оставлен как бэкап, но не используется.

**Telegram-десктоп → SOCKS5:** Настройки → Продвинутые настройки → Сетевые настройки → Тип прокси **SOCKS5**, хост `127.0.0.1`, порт `1080`, без логина/пароля. (В macOS-клиенте TG: Settings → Advanced → Connection type → Use custom proxy → SOCKS5.)

**Браузер → SOCKS5:** Расширение **SwitchyOmega** (Chrome/Edge/Firefox) → профиль «proxy» SOCKS5 `127.0.0.1:1080`. Включать только для TG/YouTube/заблокированного (остальное — напрямую, чтобы не гнать через VPS лишнее и не терять скорость). Для Safari — системный прокс: «Системные настройки → Сеть → Wi-Fi → Подробно → Прокси-серверы → SOCKS → 127.0.0.1:1080» (но тогда весь браузер через VPS — лучше SwitchyOmega в Chrome).

### 8.2 Телефон: ShadowTLS-клиент

На телефоне нужен клиент с поддержкой **ShadowTLS v3** (AmneziaVPN его **не умеет**). Подходящие: **Hiddify** или **v2rayNG** (Android), **FoXray**/**Streisand** (iOS). Вносим вручную: тип ShadowTLS, сервер `194.62.66.34:8443`, версия 3, пароль `<ST_PW — на VPS: /etc/sing-box-st/secrets>`, внутренний протокол Shadowsocks, метод `2022-blake3-aes-128-gcm`, ключ `<SS_KEY — там же>`, SNI `www.bing.com`, uTLS `chrome`. Сервер один — Mac и телефон подключаются параллельно.

> ⚠️ На телефоне это **полный туннель** (весь трафик через VPN), а не сплит, как на Mac.

> 🔒 SSH на VPS — только по ключу; root-пароль нигде вставлять не надо. Где лежит пароль — см. «Секреты».

### 8.3 Телефон: «подключено, но Telegram/приложения не работают»

Сервер тут ни при чём: `sing-box-st` корректный и для Mac работает (проверка: `curl --socks5-hostname 127.0.0.1:1080 https://api.ipify.org` → `194.62.66.34`). Значит проблема на клиенте/сети телефона. Диагноз по шагам:

**а) Живой замер на сервере (самое информативное).** Подними VPN на телефоне (статус «подключено»), открой Telegram — и на Mac выполни:
```bash
ssh root@194.62.66.34 "ss -tn state established '( sport = :8443 )' | tail -n +2"
```
- Есть соединение с внешнего IP (адрес телефона/оператора) → туннель реально поднят, дело в приложении — идём к п. б.
- Пусто → туннель не поднялся (ShadowTLS-handshake не дошёл): пересоздай подключение, проверь мобильный интернет, переподключи VPN.

**б) Что проверить в клиенте:**
1. **Режим туннеля** — «весь трафик / все приложения», не split-tunnel (Telegram не в исключениях).
2. **MTU** — если поле есть, поставь `1280`. ShadowTLS даёт овергед, на мобильных из-за этого Telegram «висит на connecting».
3. **Принудительно закрой и открой Telegram** после включения VPN (он держит старые соединения с заблокированными серверами).

**в) Если не помогло** — попробуй другой ShadowTLS-клиент (Hiddify ↔ v2rayNG ↔ FoXray) с теми же параметрами. Сервер и протокол те же.

## 9. Если что-то сломалось

| Симптом | С чего начать |
|---------|---------------|
| Бот молчит | `systemctl status back-bot` + `journalctl -u back-bot -n 50` |
| `/chat` отвечает заглушкой | Mac/Ollama недоступны: `curl http://100.72.19.121:11434/api/version` (с VPS), проверь `launchctl \| grep ollama` на Mac |
| Telegram-десктоп не работает | SOCKS5-прокси: `launchctl list \| grep local.singbox-st`, `curl --socks5-hostname 127.0.0.1:1080 https://api.ipify.org`, рестарт по §8.1; в TG проверь SOCKS5 `127.0.0.1:1080` |
| YouTube не грузит | SOCKS5-прокси (§8.1) + SwitchyOmega в браузере на `127.0.0.1:1080`; VPS-сервер: `ssh root@194.62.66.34 'systemctl status sing-box-st'` |
| Телефон: VPN «подключено», но Telegram/приложения не работают | см. §8.3: живой замер `ss`, MTU=1280, режим туннеля, перезапуск Telegram |
| «409 Conflict» в логах | где-то ещё запущен второй инстанс бота (например, на Mac) — останови его (`pkill -f main.py` на Mac) |
| Рассылка пришла дважды | не должна (sent_log + sweep); проверь, что не два бота сразу |

## 10. Оплата VPS

Тариф ₽593/мес, списание 6-го числа. Ссылка: `https://my.aeza.ru/services/602586`.
Бот сам напоминает об оплате в окне **3 дня до и в день списания** (переменные `VPS_RENEWAL_DAY`, `VPS_COST`, `VPS_PAY_URL`, `VPS_EXPIRY` в `.env`).

---

## Секреты (важно)
- **Не коммить** `.env` (там `BOT_TOKEN`, `TELEGRAPH_TOKEN`) и VPS root-пароль. `.gitignore` уже исключает `.env` и `data/`.
- На VPS секреты живут в `/root/body-development/.env` (доступ только root).
- SSH на VPS — **только по ключу** (`~/.ssh/id_ed25519`); вход по паролю отключён.
- **Root-пароль от VPS** (ротейтнут 2026-07-11) хранится в **macOS Keychain**, не plaintext: достать командой `security find-generic-password -a kagruzdev -s "vps-root-194.62.66.34" -w` (при первом чтении — GUI-промпт «Always Allow»). Нужен только для noVNC-консоли хостинга в крайнем случае.
