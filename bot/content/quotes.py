"""Цитаты из «Move Your DNA» (Katy Bowman, 2nd ed.) — по дням программы.

Каждый день получает: понятие книги (concept — связка с темой дня, мой пересказ)
и вербатим-цитату (quote — оригинальный английский, без перевода = без потери
контекста) с указанием страницы. Источник анализа — data/book_synthesis.md.

Распределение покрывает ВСЕ ключевые понятия книги (механотрансдукция, load≠weight,
movement vs exercise, sticky spots, alignment≠posture, diseases of captivity,
гипертоничность/релизы, стопа-сенсор, целостный таз, присед-путь, Kegels и т.д.).
"""
from __future__ import annotations

# day -> {"concept": str, "quote": str, "page": int}
QUOTES: dict[int, dict] = {
    1: {
        "concept": "Движение — это питание, а не «упражнения». Ты — то, как ты двигаешься.",
        "quote": "Movement, like food, is not optional.",
        "page": 22,
    },
    2: {
        "concept": "Форма костей и изгибов — это autobiography твоих нагрузок.",
        "quote": "It is through your choices of movement and the cellular loads these choices create that your body becomes your autobiography.",
        "page": 45,
    },
    3: {
        "concept": "Сердце — не единственный насос: работающие мышцы сами тянут кровь к тканям.",
        "quote": "The ‘heart-pump’ model of the circulatory system … is not ‘how the body works,’ but how the body operates in a movement drought.",
        "page": 62,
    },
    4: {
        "concept": "Спазм и «болезни поведения» — нормальный ответ тела на «зоопарк» современной среды.",
        "quote": "We, like these floppy-finned orcas, are animals in captivity, and our tissues are not suited to the loads created through the way we move in our modern habitat.",
        "page": 34,
    },
    5: {
        "concept": "«Каменность» — это sticky spots: от обездвиживания волокна склеиваются.",
        "quote": "The cells in sticky areas of your body regenerate without movement context … and the areas just outside of the sticky spot experience unnaturally high loads.",
        "page": 74,
    },
    6: {
        "concept": "Механотрансдукция: тело буквально перестраивается под нагрузки.",
        "quote": "It is via the process of mechanotransduction that our physical self adapts (in shape) to our experience of the physical world.",
        "page": 24,
    },
    7: {
        "concept": "Стопа — сенсорный орган; проприоцепция гаснет от обездвиженности.",
        "quote": "Feet are extremely dexterous … the sole of your foot is, like your nose or eyes, a sensory organ.",
        "page": 90,
    },
    8: {
        "concept": "Правая «каменная», левая слабая — асимметрия от доминантной руки и позы.",
        "quote": "You’ve developed asymmetrical tissue strengths due to repetitive, low-force patterning in one arm, and you’ve got significant weakness in both.",
        "page": 115,
    },
    9: {
        "concept": "Фасция — единая 3D-сеть; нагрузка в одной зоне гасит и деформирует соседние.",
        "quote": "A dense, fibrous connective tissue that permeates the body and forms a continuous, three-dimensional matrix that functions as a whole-body support system.",
        "page": 74,
    },
    10: {
        "concept": "Кифоз и сутулость — наш «floppy fin»: спину держит тонус от движения руками.",
        "quote": "Kyphosis is our floppy fin.",
        "page": 116,
    },
    11: {
        "concept": "«Спящие» ягодицы = потерянная экстензия бедра; будит их ходьба, не изоляция.",
        "quote": "The seemingly bottomless pool of glute-less people matches up exactly to the number of those without hip extension.",
        "page": 178,
    },
    12: {
        "concept": "Кор и lateral hip держат таз; слабая сторона не справляется на одной ноге.",
        "quote": "Walking is essentially one bout of single-leg balance followed by another … the lateral hip musculature of this leg must be strong enough to carry the load created by the rest of the body.",
        "page": 174,
    },
    13: {
        "concept": "Мячик — мобилизация костей стопы/фасций: «stepping on lumps and bumps».",
        "quote": "Mobilizing the bones between the feet … they are mobilized better through stepping on lumps and bumps.",
        "page": 100,
    },
    14: {
        "concept": "Аппликатор = пассивная нагрузка; она тоже деформирует клетки.",
        "quote": "The load is not the wind. The load is the effects created by the wind.",
        "page": 24,
    },
    15: {
        "concept": "Час спорта не отменяет 8 часов сидения; статика — отдельный риск.",
        "quote": "Sitting time itself is a risk factor for cardiovascular disease, even in those who exercise regularly. Regular bouts of exercise do not undo the effect that sitting has on the body.",
        "page": 63,
    },
    16: {
        "concept": "Ты никогда не «не в форме» — ты всегда в форме, созданной привычками.",
        "quote": "Your body is never ‘out of shape’; it is always in a shape created by how you have moved up to this very moment.",
        "page": 42,
    },
    17: {
        "concept": "Автоматизирует дыхание частота по всему дню, а не разовая тренировка.",
        "quote": "Greater frequency (spreading the repetition throughout the day rather than doing it twenty times all at once) tends to yield better results.",
        "page": 87,
    },
    18: {
        "concept": "Укороченные сгибатели (psoas) тянут таз — это и есть «не-приседание».",
        "quote": "The very act of ‘not squatting’ may be as important in terms of creating a biomechanical environment as squatting itself.",
        "page": 177,
    },
    19: {
        "concept": "Выпад/растяжка сгибателей — переход пошагово: «too far, too fast» = боль.",
        "quote": "Pain is often an indication that you’ve gone too far, too fast.",
        "page": 79,
    },
    20: {
        "concept": "Мостик/присед — это путь и опыт, не поза; вертикальная голень = ягодицы.",
        "quote": "A squat is much more than a position; a squat is an experience.",
        "page": 186,
    },
    21: {
        "concept": "Перекрёстный синдром = stress risers: сильная зона рядом со слабой.",
        "quote": "Having strong, regularly used parts next to underused (or overused) weak ones can actually increase tissue damage by creating a natural stress riser.",
        "page": 53,
    },
    22: {
        "concept": "Структурная адаптация: тело подгоняет длину мышц под частую позу.",
        "quote": "Your body adapts to where you spend the most time, making it easier (i.e., taking less energy) to do what you do most often.",
        "page": 72,
    },
    23: {
        "concept": "Новая осанка — это alignment, а не замирание в «правильной» позе.",
        "quote": "It is often our determination to maintain a ‘good’ fixed posture that is undermining our health.",
        "page": 86,
    },
    24: {
        "concept": "Эргономика + вставание с пола без рук — мощный прогноз здоровья.",
        "quote": "The more you need to use your hands and knees to get up from the floor, the greater your risk of dying from all causes.",
        "page": 108,
    },
    25: {
        "concept": "Микро-паузы — это движение (не упражнение), распределённое по дню.",
        "quote": "Exercise is movement, but movement is not always exercise.",
        "page": 56,
    },
    26: {
        "concept": "Эффект стимуляции локален: кровь и тонус идут только в работающую зону.",
        "quote": "The effect of exercise—specifically the increase of oxygen delivery—is not systemic.",
        "page": 62,
    },
    27: {
        "concept": "Тепло/вибрация/повязка — это release; среда нагружает даже в покое.",
        "quote": "Your pillow and mattress are subversive immobilizing devices issued at birth.",
        "page": 150,
    },
    28: {
        "concept": "Хронический стресс «зоопарка» держит гипертонус; лес/тишина снижают кортизол.",
        "quote": "Forest-bathing has been shown to promote lower concentrations of cortisol, lower pulse rate and blood pressure, and a reduction of ‘technostress.’",
        "page": 151,
    },
    29: {
        "concept": "Скелет — «живая история»; метрики 1–10 честнее памяти о «как обычно».",
        "quote": "Skeletons are a sort of ‘living story’ you are continuously writing.",
        "page": 45,
    },
    30: {
        "concept": "Месяц — это метаморфоза: ты перестраиваешь тело нагрузками, как гусеница.",
        "quote": "Now, go ahead and move your DNA.",
        "page": 201,
    },
}


def get_quote(day: int) -> dict | None:
    """Цитата по номеру дня (1..30). Вне диапазона — ближайшая."""
    if day < 1:
        day = 1
    if day > 30:
        day = 30
    return QUOTES.get(day)
