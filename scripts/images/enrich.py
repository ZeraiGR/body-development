"""Обогащение статей картинками: заменяет [РИСУНОК: ...] на реальные схемы.

Хостинг — catbox.moe (HTTPS), т.к. Telegraph отдаёт страницы по HTTPS и блокирует
HTTP-картинки (mixed content). Для каждой заглушки [РИСУНОК: ...] ищем совпадение
по ключевым словам темы: есть — вставляем ![подпись](url); нет — убираем заглушку.

Переиспользуемо: при добавлении схем повторный запуск подхватит оставшиеся [РИСУНОК].
Запуск:  python scripts/images/enrich.py   (из корня проекта)
"""
from __future__ import annotations

import glob
import json
import re

# Постоянные HTTPS-URL схем на GitHub raw (открывается в РФ, в отличие от catbox).
RAW = "https://raw.githubusercontent.com/ZeraiGR/body-development/main/assets/images"
IMG = {
    "disc_pressure": f"{RAW}/disc_pressure.png",
    "disc_structure": f"{RAW}/disc_structure.png",
    "breathing_iap": f"{RAW}/breathing_iap.png",
    "posture_chain": f"{RAW}/posture_chain.png",
    "asymmetry": f"{RAW}/asymmetry.png",
    "mfr_trigger": f"{RAW}/mfr_trigger.png",
    "hip_flexors": f"{RAW}/hip_flexors.png",
    "glutes_bridge": f"{RAW}/glutes_bridge.png",
    "microbreak": f"{RAW}/microbreak.png",
}

# (ключевые_слова_темы, url, подпись)
LIBRARY = [
    (["давление в диске", "% от стоя", "давление, %", "nachemson", "wilke",
      "столбчатая диаграмма давления", "цилиндр давления в разрезе"],
     IMG["disc_pressure"], "Давление в диске, % от стояния (Nachemson/Wilke)"),
    (["строение диска", "строение межпозв", "пульпозное", "фиброзное кольцо",
      "губка dis", "диск в разрезе", "ядро и кольцо"],
     IMG["disc_structure"], "Строение межпозвоночного диска (губка, ~80% вода)"),
    (["диафрагм", "iap", "внутрибрюшное", "баллон", "мышечный корсет", "корсет",
      "поперечная мышца живота", "дыхание как", "тазовое дно", "купол диафрагмы",
      "mcgill", "большая тройка", "цилиндр кора", "core"],
     IMG["breathing_iap"], "Дыхание как внутренний корсет (IAP)"),
    (["лордоз", "кифоз", "голова вперёд", "осанка как цеп", "цепочк",
      "сутулость", "зазор поясницы", "wall test", "у стены", "грудной отдел",
      "плавник", "thoracic", "ход", "походка", "gait", "стопа как сенсор",
      "проприоцепц"],
     IMG["posture_chain"], "Осанка как цепочка: лордоз → кифоз → голова вперёд"),
    (["асимметр", "сдвиг влево", "каменная правая", "гипертонус прав",
      "слабая левая", "правая сторона", "корпус сдвинут", "битое колесо"],
     IMG["asymmetry"], "Асимметрия: сдвиг влево + каменная правая"),
    (["мфр", "миофасциальн", "триггерн", "мяч для", "релиз", "точечное давление",
      "аппликатор", "trigger point", "гипертонус"],
     IMG["mfr_trigger"], "Миофасциальный релиз: мяч на триггерной точке"),
    (["сгибател", "наклон таза", "передний наклон", "подвздошно-пояснич",
      "psoas", "посас", "мышца-звезда", "тросы которые тянут"],
     IMG["hip_flexors"], "Сгибатели бедра тянут таз вперёд"),
    (["ягодич", "ягодиц", "мостик", "chair squat", "присед", "активация ягод",
      "спящие вахтёры", "подъёмники", "задняя передача", "экстензия бедра"],
     IMG["glutes_bridge"], "Ягодичный мостик: будим спящие ягодицы"),
    (["45/15", "45-15", "микропауз", "правило 20-8", "20-8", "движение против упражн",
      "перерыв", "встань", "habit", "стек", "hook", "привычк", "наслаиван",
      "эргоном", "рабочее место", "дневник", "log", "трек", "ощущени",
      "сигнализаци", "сенситизац", "механотрансдукц", "перестраива"],
     IMG["microbreak"], "Правило 45/15: движение против упражнения"),
]


def _match(desc: str) -> tuple[str, str] | None:
    low = desc.lower()
    for kws, url, cap in LIBRARY:
        if any(k in low for k in kws):
            return url, cap
    return None


def enrich_text(b: str) -> tuple[str, int, int]:
    placed = removed = 0

    def repl(m):
        nonlocal placed, removed
        r = _match(m.group(0))
        if r:
            url, cap = r
            placed += 1
            return f"![{cap}]({url})"
        removed += 1
        return ""  # убрать непарную заглушку

    b = re.sub(r"\[РИСУНОК:[^\]]*\]", repl, b)
    b = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", b)
    return b, placed, removed


def main() -> None:
    total_placed = total_removed = 0
    for f in sorted(glob.glob("data/articles/day_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        b = d["body_markdown"]
        new, placed, removed = enrich_text(b)
        if new != b:
            d["body_markdown"] = new
            json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            imgs = sum(new.count(u) for u in IMG.values())
            print(f"{f.split('/')[-1]}: +{placed}, всего {imgs}")
            total_placed += placed
            total_removed += removed
    print(f"ИТОГО: расставлено {total_placed}, удалено заглушек {total_removed}")


if __name__ == "__main__":
    main()
