"""Генератор точных схем для статей курса (Pillow).

Единый чистый стиль: белый фон, тёмный текст, цветовая шкала нагрузки
(зелёный/жёлтый/красный). Шрифт — с кириллицей (Arial Unicode на macOS).
Каждая функция возвращает путь к готовому PNG.

Только программные схемы (графики/диаграммы/подписанные фигуры) — они точные
и единообразные. Анатомию/метафоры рисует AI (см. ai_pollinations.py).
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

# ── палитра ─────────────────────────────────────────────────────────────── #
BG = (255, 255, 255)
TEXT = (31, 41, 51)
SUB = (90, 100, 110)
GREEN = (46, 158, 91)
YELLOW = (212, 160, 23)
RED = (214, 69, 69)
GRID = (228, 231, 235)

_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/Library/Fonts/Arial.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in _FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _level(pct: int) -> tuple:
    if pct <= 60:
        return GREEN
    if pct <= 140:
        return YELLOW
    return RED


def disc_pressure_bars(out: str = "/tmp/img_disc_pressure.png") -> str:
    """Сравнение давления в поясничном диске (Nachemson/Wilke), стоя = 100%."""
    rows = [
        ("Лёжа на спине", 15, "единственная настоящая разгрузка"),
        ("Стоя прямо", 100, "база, нейтральное положение"),
        ("Сидя прямо, без опоры", 140, "«стараться сидеть прямо»"),
        ("Сидя ссутулившись", 190, "почти вдвое больше стоя"),
        ("Наклон + ротация (поднять с поворотом)", 275, "опасная пиковая поза"),
    ]
    W, H = 1100, 640
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title_f, lab_f, val_f, sub_f = _font(30), _font(22), _font(22), _font(16)
    d.text((40, 24), "Давление в диске (% от стоя)", fill=TEXT, font=title_f)
    d.text((40, 62), "Nachemson 1981 · Wilke, Spine 24(8), 1999", fill=SUB, font=sub_f)
    top = 110
    row_h = 92
    max_pct = 300
    chart_x = 470
    chart_w = W - chart_x - 40
    for i, (label, pct, note) in enumerate(rows):
        y = top + i * row_h
        d.text((40, y + 4), label, fill=TEXT, font=lab_f)
        d.text((40, y + 34), note, fill=SUB, font=sub_f)
        # шкала-подложка
        d.rectangle([chart_x, y + 14, chart_x + chart_w, y + 46], fill=GRID)
        # столбец
        bw = int(chart_w * min(pct, max_pct) / max_pct)
        d.rectangle([chart_x, y + 14, chart_x + bw, y + 46], fill=_level(pct))
        d.text((chart_x + bw + 10, y + 16), f"{pct}%", fill=TEXT, font=val_f)
    img.save(out)
    return out


def disc_structure(out: str = "/tmp/img_disc_structure.png") -> str:
    """Строение межпозвоночного диска: два позвонка + диск (ядро/кольцо), ~80% вода."""
    W, H = 900, 560
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title_f, lab_f, sub_f, small_f = _font(28), _font(20), _font(16), _font(15)
    d.text((40, 24), "Межпозвоночный диск — губка", fill=TEXT, font=title_f)
    d.text((40, 60), "нет кровеносных сосудов → питание только через смену нагрузки", fill=SUB, font=sub_f)

    bone = (235, 230, 220)
    ring = (255, 250, 240)        # фиброзное кольцо (внешний слой диска)
    core = (120, 170, 215)        # пульпозное ядро (гель внутри)
    cx = 360
    # верхний позвонок
    d.rounded_rectangle([cx - 150, 130, cx + 150, 200], radius=14, fill=bone, outline=SUB)
    # диск (между позвонками)
    d.ellipse([cx - 140, 200, cx + 140, 300], fill=ring, outline=(200, 195, 185))
    d.ellipse([cx - 60, 222, cx + 60, 282], fill=core)
    # нижний позвонок
    d.rounded_rectangle([cx - 150, 300, cx + 150, 370], radius=14, fill=bone, outline=SUB)

    # стрелки давления сверху/снизу
    arrow = (214, 69, 69)
    for x in (cx - 90, cx, cx + 90):
        d.line([x, 95, x, 128], fill=arrow, width=4)
        d.polygon([(x - 7, 122), (x + 7, 122), (x, 130)], fill=arrow)
        d.line([x, 405, x, 372], fill=arrow, width=4)
        d.polygon([(x - 7, 378), (x + 7, 378), (x, 370)], fill=arrow)
    d.text((cx - 70, 70), "давление", fill=arrow, font=small_f)

    # подписи с выносками
    def label(x_from, y_from, x_to, y_to, text, sub=None):
        d.line([x_from, y_from, x_to, y_to], fill=SUB, width=2)
        d.text((x_to, y_to - 10), text, fill=TEXT, font=lab_f)
        if sub:
            d.text((x_to, y_to + 14), sub, fill=SUB, font=sub_f)

    label(cx + 140, 230, 560, 200, "фиброзное кольцо", "плотные волокна (внешний слой)")
    label(cx - 30, 252, 560, 300, "пульпозное ядро", "гель, ~80% вода")
    label(cx + 150, 165, 560, 400, "позвонок", "кость")

    d.text((40, 470), "Сжатие → выдавливает отработанную жидкость. Разгрузка → всасывает свежую.",
           fill=TEXT, font=sub_f)
    d.text((40, 496), "Без смены нагрузки диск «не дышит» — отсюда проблема долгого сидения.",
           fill=SUB, font=sub_f)
    img.save(out)
    return out


def breathing_iap(out: str = "/tmp/img_breathing_iap.png") -> str:
    """Внутрибрюшное давление (IAP): диафрагма + мышечный корсет + тазовое дно = баллон-опора для позвоночника."""
    W, H = 940, 620
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title_f, lab_f, sub_f, small_f = _font(28), _font(20), _font(16), _font(15)
    d.text((40, 24), "Дыхание как внутренний корсет (IAP)", fill=TEXT, font=title_f)
    d.text((40, 60), "диафрагма + поперечная мышца + тазовое дно = баллон, на который опирается позвоночник", fill=SUB, font=sub_f)
    cx = 300
    # баллон IAP (цилиндр)
    iap = (120, 170, 215)
    d.rounded_rectangle([cx - 110, 200, cx + 110, 410], radius=40, fill=iap)
    d.ellipse([cx - 110, 188, cx + 110, 232], fill=iap)     # диафрагма (купол сверху)
    d.ellipse([cx - 110, 378, cx + 110, 422], fill=(170, 140, 120))  # тазовое дно
    # столб позвонков на баллоне
    for i in range(4):
        d.rounded_rectangle([cx - 24, 120 - i * 18, cx + 24, 134 - i * 18], radius=4, fill=(235, 230, 220), outline=SUB)
    # стрелка нагрузки гасится о баллон
    d.line([cx, 40, cx, 116], fill=RED, width=4)
    d.polygon([(cx - 7, 110), (cx + 7, 110), (cx, 118)], fill=RED)
    d.text((cx + 14, 50), "нагрузка\nсверху", fill=RED, font=small_f)
    # подписи
    def lbl(xf, yf, xt, yt, t, s=None):
        d.line([xf, yf, xt, yt], fill=SUB, width=2)
        d.text((xt, yt - 10), t, fill=TEXT, font=lab_f)
        if s:
            d.text((xt, yt + 14), s, fill=SUB, font=sub_f)
    lbl(cx + 110, 210, 470, 180, "диафрагма", "купол, опускается на вдохе")
    lbl(cx + 90, 300, 470, 300, "поперечная мышца", "боковые стенки баллона")
    lbl(cx, 415, 470, 410, "тазовое дно", "нижняя стенка")
    d.text((40, 470), "На вдохе животом: баллон наполняется → давление ↑ → позвоночник опирается, поясница разгружается.",
           fill=TEXT, font=sub_f)
    d.text((40, 496), "Грудное дыхание: баллон сдут → поясницу держат мышцы снаружи → перенапряжение.",
           fill=SUB, font=sub_f)
    img.save(out)
    return out


def posture_chain(out: str = "/tmp/img_posture_chain.png") -> str:
    """Цепь нарушений осанки: гиперлордоз + кифоз + выдвинутая голова — единая цепочка."""
    W, H = 940, 560
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title_f, lab_f, sub_f = _font(28), _font(20), _font(16)
    d.text((40, 24), "Осанка как цепочка: одно тянет другое", fill=TEXT, font=title_f)
    d.text((40, 60), "гиперлордоз → кифоз → голова вперёд — это одна линия, а не три проблемы", fill=SUB, font=sub_f)
    # силуэт сбоку (упрощённый): линия тела
    sk = (90, 100, 110)
    head = (470, 150)
    d.ellipse([head[0] - 26, head[1] - 26, head[0] + 26, head[1] + 26], fill=sk)  # голова вперёд
    # шея (вперёд), грудь (сутулая), поясница (прогиб), таз
    pts = [(head[0], head[1] + 26), (head[0] + 6, 210), (head[0] - 26, 270),   # шея→грудь(сутулая, назад)
           (head[0] - 10, 340), (head[0] + 20, 410)]                            # поясница(прогиб)→таз
    for i in range(len(pts) - 1):
        d.line([pts[i], pts[i + 1]], fill=sk, width=10)
    #标注ы отклонений
    d.line([head[0] - 60, 150, head[0] - 30, 150], fill=RED, width=2)
    d.text((head[0] - 150, 142), "голова вперёд", fill=RED, font=lab_f)
    d.arc([head[0] - 40, 250, head[0] + 40, 350], 200, 360, fill=RED, width=3)  # кифоз (горб назад)
    d.text((head[0] - 230, 270), "кифоз (грудь назад)", fill=RED, font=lab_f)
    d.arc([head[0] - 10, 320, head[0] + 70, 410], 20, 180, fill=RED, width=3)  # лордоз (прогиб вперёд)
    d.text((head[0] + 70, 350), "гиперлордоз (поясница провалена)", fill=RED, font=lab_f)
    # вертикаль (идеальная ось)
    d.line([head[0] - 60, 120, head[0] - 60, 430], fill=GREEN, width=2)
    d.text((head[0] - 130, 110), "идеальная ось", fill=GREEN, font=sub_f)
    d.text((40, 470), "Сидение «заколачивает» эту цепь глубже с каждым часом. Тянуть одно звено без других — мало.",
           fill=TEXT, font=sub_f)
    img.save(out)
    return out


def asymmetry(out: str = "/tmp/img_asymmetry.png") -> str:
    """Асимметрия: корпус сдвинут влево, правая сторона гипертонична, левая слабая."""
    W, H = 900, 560
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title_f, lab_f, sub_f = _font(28), _font(20), _font(16)
    d.text((40, 24), "Твоя асимметрия: сдвиг влево + каменная правая", fill=TEXT, font=title_f)
    d.text((40, 60), "правая несёт перегруз (гипертонус), левая заторможена", fill=SUB, font=sub_f)
    cx = 430
    # вертикальная ось таза
    d.line([cx, 150, cx, 440], fill=GRID, width=2)
    # корпус — сдвинут влево от оси
    d.rounded_rectangle([cx - 120, 180, cx + 60, 400], radius=30, fill=(230, 230, 235), outline=SUB)
    # правая сторона — красная (гипертонус)
    d.rectangle([cx + 20, 190, cx + 60, 395], fill=(214, 69, 69))
    d.text((cx + 70, 250), "ПРАВАЯ", fill=(214, 69, 69), font=lab_f)
    d.text((cx + 70, 278), "гипертонус,\nтриггерные точки,\nнесёт перегруз", fill=SUB, font=sub_f)
    # левая — серая (слабая)
    d.text((cx - 250, 250), "ЛЕВАЯ", fill=SUB, font=lab_f)
    d.text((cx - 250, 278), "заторможена,\nслабая,\n«выключена»", fill=SUB, font=sub_f)
    # стрелка сдвига влево
    d.line([cx - 60, 150, cx - 120, 150], fill=RED, width=3)
    d.polygon([(cx - 114, 144), (cx - 114, 156), (cx - 124, 150)], fill=RED)
    d.text((cx - 130, 120), "сдвиг корпуса", fill=RED, font=lab_f)
    # диск: одна половина сжата сильнее
    d.ellipse([cx - 40, 410, cx + 40, 450], fill=(255, 250, 240), outline=SUB)
    d.rectangle([cx, 411, cx + 39, 449], fill=(214, 69, 69))
    d.text((cx - 200, 420), "диск сжат неравномерно:\nправая половина голодает", fill=SUB, font=sub_f)
    d.text((40, 490), "Решение — односторонняя работа на левую + МФР на правую (не «качать спину» вообще).",
           fill=TEXT, font=sub_f)
    img.save(out)
    return out


def mfr_trigger(out: str = "/tmp/img_mfr_trigger.png") -> str:
    """Миофасциальный релиз: мяч на триггерной точке мышцы — точечное давление."""
    W, H = 900, 480
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title_f, lab_f, sub_f = _font(28), _font(20), _font(16)
    d.text((40, 24), "МФР: мяч на триггерной точке", fill=TEXT, font=title_f)
    # мышца (полоса)
    d.rounded_rectangle([120, 250, 720, 330], radius=30, fill=(210, 175, 175), outline=SUB)
    # триггерная точка (узел)
    d.ellipse([340, 250, 400, 330], fill=(214, 69, 69))
    d.text((350, 200), "триггерная точка", fill=(214, 69, 69), font=lab_f)
    # мяч
    d.ellipse([330, 150, 410, 230], fill=(60, 130, 200))
    d.text((420, 175), "мяч (теннисный/МФР)", fill=TEXT, font=lab_f)
    # стрелка давления
    d.line([370, 232, 370, 248], fill=RED, width=4)
    d.polygon([(363, 244), (377, 244), (370, 250)], fill=RED)
    d.text((40, 380), "60-90 секунд точечного давления → точка размягчается, кровоток восстанавливается.",
           fill=TEXT, font=sub_f)
    img.save(out)
    return out


def hip_flexors_pelvis(out: str = "/tmp/img_hip_flexors.png") -> str:
    """Сгибатели бедра тянут таз вперёд (передний наклон) при долгом сидении."""
    W, H = 940, 540
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title_f, lab_f, sub_f = _font(28), _font(20), _font(16)
    d.text((40, 24), "Сгибатели бедра тянут таз вперёд", fill=TEXT, font=title_f)
    d.text((40, 60), "долгое сидение укорачивает сгибатели → передний наклон таза → поясница переразгибается",
           fill=SUB, font=sub_f)
    # таз (нейтральный vs передний наклон)
    for i, (cx, cap, col) in enumerate([(260, "нейтрально", GREEN), (640, "передний наклон", RED)]):
        d.ellipse([cx - 70, 220, cx + 70, 340], fill=None, outline=col, width=3)
        # позвоночник
        ang = 0 if i == 0 else 15
        d.line([cx, 220, cx + ang, 120], fill=col, width=6)
        # сгибатели (спереди)
        d.line([cx - 40, 280, cx - 110, 200], fill=col if i else SUB, width=4)
        d.text((cx - 95, 360), cap, fill=col, font=lab_f)
    # стрелка натяжения сгибателей
    d.line([530, 240, 560, 220], fill=RED, width=3)
    d.text((470, 180), "натянутые\nсгибатели", fill=RED, font=sub_f)
    d.text((40, 430), "Решение: растяжка сгибателей + активация ягодиц (ягодицы тянут таз назад).",
           fill=TEXT, font=sub_f)
    img.save(out)
    return out


def glutes_bridge(out: str = "/tmp/img_glutes_bridge.png") -> str:
    """Ягодичный мостик: активация ягодиц (они спят от сидения) — тянут таз назад."""
    W, H = 940, 460
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title_f, lab_f, sub_f = _font(28), _font(20), _font(16)
    d.text((40, 24), "Ягодичный мостик: будим спящие ягодицы", fill=TEXT, font=title_f)
    # силуэт мостика (голова-плечи-таз-колени подняты)
    SK = (90, 100, 110)
    d.ellipse([140, 220, 180, 260], fill=SK)  # голова
    pts = [(160, 250), (250, 290), (400, 250), (520, 240), (620, 300)]  # плечи→таз→колени
    for i in range(len(pts) - 1):
        d.line([pts[i], pts[i + 1]], fill=SK, width=10)
    # ягодицы (в тазе)
    d.ellipse([380, 230, 440, 270], fill=(210, 130, 130))
    d.text((370, 180), "ягодицы включены", fill=(210, 130, 130), font=lab_f)
    d.text((40, 350), "Ягодицы тянут таз назад → выравнивают наклон → разгружают поясницу.",
           fill=TEXT, font=sub_f)
    img.save(out)
    return out


def microbreak_4515(out: str = "/tmp/img_microbreak.png") -> str:
    """Правило 45/15 (и 20-8): движение против упражнения — частые микропаузы."""
    W, H = 940, 420
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title_f, lab_f, sub_f = _font(28), _font(20), _font(16)
    d.text((40, 24), "Правило 45/15 — движение, а не упражнение", fill=TEXT, font=title_f)
    # таймлайн: блоки 45 работа / 15 движение
    x = 60
    for i in range(4):
        d.rectangle([x, 140, x + 150, 220], fill=(60, 130, 200))
        d.text((x + 30, 165), "45 мин\nработа", fill="white", font=sub_f)
        d.rectangle([x + 155, 140, x + 200, 220], fill=GREEN)
        d.text((x + 158, 165), "15\nдвиж.", fill="white", font=sub_f)
        x += 210
    d.text((40, 270), "Лучше 8 секунд каждые 20 минут, которые повторишь, чем 3 минуты, которые бросишь.",
           fill=TEXT, font=sub_f)
    d.text((40, 300), "Движение в течение дня (50 ч сидения vs 3 ч зала) выигрывает у разовых тренировок.",
           fill=SUB, font=sub_f)
    img.save(out)
    return out


if __name__ == "__main__":
    import sys

    fn = sys.argv[1] if len(sys.argv) > 1 else "disc_pressure_bars"
    fns = {
        "disc_pressure_bars": disc_pressure_bars,
        "disc_structure": disc_structure,
        "breathing_iap": breathing_iap,
        "posture_chain": posture_chain,
        "asymmetry": asymmetry,
        "mfr_trigger": mfr_trigger,
        "hip_flexors_pelvis": hip_flexors_pelvis,
        "glutes_bridge": glutes_bridge,
        "microbreak_4515": microbreak_4515,
    }
    out_fn = fns.get(fn)
    if out_fn:
        print(out_fn())
    else:
        print("unknown:", fn, "| available:", ", ".join(fns))
