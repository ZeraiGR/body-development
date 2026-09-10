#!/bin/bash
# spine20ctl.sh — управление напоминанием «правило 20-8» (launchd LaunchAgent).
#
#   ./spine20ctl.sh install    — установить и запустить (грузится при логине, переживает сон)
#   ./spine20ctl.sh uninstall  — полностью удалить
#   ./spine20ctl.sh on         — включить (после off), не переустанавливая
#   ./spine20ctl.sh off        — пауза (без удаления)
#   ./spine20ctl.sh status     — работает ли сейчас
#   ./spine20ctl.sh test       — отправить одну нотификацию сейчас (проверка)
set -euo pipefail

LABEL="com.bodydev.spine20"
PLIST_NAME="$LABEL.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTIFY="$SCRIPT_DIR/spine20-notify.sh"
AGENT="$HOME/Library/LaunchAgents/$PLIST_NAME"
DOMAIN="gui/$UID"

gen_plist() {
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$AGENT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$NOTIFY</string>
    </array>
    <key>StartInterval</key>
    <integer>1200</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/tmp/spine20.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/spine20.err</string>
</dict>
</plist>
EOF
}

cmd_install() {
  [ -x "$NOTIFY" ] || chmod +x "$NOTIFY"
  gen_plist
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$AGENT"
  echo "✓ Установлено. Напоминание каждые 20 минут, автозапуск при логине."
  echo "  Первое напоминание — через 20 минут."
  echo "  Проверить сейчас:    $0 test"
}

cmd_uninstall() {
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$AGENT"
  echo "✓ Полностью удалено (LaunchAgent убран, plist стёрт)."
}

cmd_on() {
  if [ ! -f "$AGENT" ]; then echo "Сначала: $0 install"; exit 1; fi
  launchctl bootstrap "$DOMAIN" "$AGENT" 2>/dev/null || launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
  echo "✓ Включено."
}

cmd_off() {
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  echo "✓ На паузе (plist остался, при перезагрузке/логине снова поднимется — используй uninstall для полного отключения)."
}

cmd_status() {
  if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    echo "● работает (каждые 20 мин)"
  elif [ -f "$AGENT" ]; then
    echo "○ установлен, но не загружен → $0 on"
  else
    echo "○ не установлен → $0 install"
  fi
}

cmd_test() {
  [ -x "$NOTIFY" ] || chmod +x "$NOTIFY"
  bash "$NOTIFY"
  echo "(нотификация отправлена — если не появилась, см. README, раздел «Разрешения»)"
}

case "${1:-}" in
  install)   cmd_install ;;
  uninstall) cmd_uninstall ;;
  on)        cmd_on ;;
  off)       cmd_off ;;
  status)    cmd_status ;;
  test)      cmd_test ;;
  *) echo "Использование: $0 {install|uninstall|on|off|status|test}"; exit 1 ;;
esac
