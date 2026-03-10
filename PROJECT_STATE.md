# PROJECT_STATE.md

> Документ фиксирует текущее состояние реализации на момент 2026-03-10.
> Описывает только то, что реально существует в коде.

---

## 1. Назначение проекта

**Farm Guardian** — Telegram-бот для управления фермерским хозяйством.  
Бот позволяет фермеру через Telegram:
- вести журнал наблюдений и записей по ферме,
- вести карточки отдельных животных,
- получать автоматические уведомления о погодных рисках (морозы),
- просматривать ветеринарные протоколы (расписание процедур по дням).

---

## 2. Структура проекта

```
Ферма/
├── start_farm_guardian.ps1        # Скрипт запуска (PowerShell)
├── start_guardian.bat             # Скрипт запуска (BAT)
├── PROJECT_STATE.md
└── farm_guardian/
    ├── bot.py                     # Точка входа бота
    ├── app_context.py             # Глобальный контекст приложения
    ├── config.py                  # Загрузка конфигурации
    ├── controller.py              # Бизнес-логика: построение и выполнение планов записи
    ├── file_executor.py           # Запись данных в Markdown-файлы
    ├── pending_store.py           # Хранилище ожидающих подтверждения планов
    ├── protocols.py               # Загрузка и отображение ветеринарных протоколов
    ├── llm_client.py              # Клиент AnythingLLM (не интегрирован в бота)
    ├── weather_collector.py       # Сборщик погоды (запускается отдельно)
    ├── weather_monitor.py         # Старая версия монитора погоды (не используется ботом)
    ├── get_slug.py                # Утилита: получить slug воркспейса AnythingLLM
    ├── test_llm.py                # Тест LLM-клиента
    ├── test_protocols.py          # Тест протоколов
    ├── handlers/
    │   ├── __init__.py
    │   ├── core.py                # Обработчики /start, /ping
    │   ├── farm.py                # Обработчики /note, /observe
    │   ├── confirm.py             # Обработчики /yes, /no
    │   └── weather.py             # Обработчики /weather_on, /weather_off, /weather_now
    ├── weather/
    │   ├── __init__.py
    │   ├── monitor.py             # Фоновый монитор погоды (поток)
    │   ├── rules.py               # Классификация погоды, форматирование сообщений
    │   └── subscribers.py        # Управление подписчиками погодных уведомлений
    ├── config/
    │   └── secrets.json           # Токены и настройки (не в репозитории)
    ├── storage/
    │   ├── pending.json           # Ожидающие подтверждения планы (runtime)
    │   └── weather_subscribers.json  # Список подписчиков (runtime)
    └── farm_memory/
        ├── animals/               # Карточки животных (старый формат)
        ├── resources/
        │   ├── animals.json       # Словарь псевдонимов животных
        │   ├── feed.md            # Учёт кормов
        │   └── animals/          # Карточки животных (активный формат)
        │       ├── masha.md
        │       ├── plusha.md
        │       └── fedor.md
        ├── resources/journal/     # Дневные журналы по месяцам
        │   ├── 2026-02/
        │   └── 2026-03/
        ├── protocols/             # Ветеринарные протоколы (YAML)
        │   ├── calves/
        │   ├── cattle/
        │   ├── pigs/
        │   └── other/
        ├── medical_reference/     # Справочные Markdown-файлы по протоколам
        │   ├── calves/
        │   ├── cattle/
        │   └── pigs/
        ├── journal/               # Старые журналы (отдельная папка)
        ├── sensors/
        │   └── weather.json       # Текущие данные погоды (пишет collector)
        └── system/
            ├── animal_template.md
            └── journal_template.md
```

---

## 3. Точки входа

| Файл | Способ запуска | Назначение |
|---|---|---|
| [`farm_guardian/bot.py`](farm_guardian/bot.py) | `python bot.py` | Основной процесс Telegram-бота |
| [`start_guardian.bat`](start_guardian.bat) | Двойной клик / cmd | Активирует venv и запускает `bot.py` |
| [`start_farm_guardian.ps1`](start_farm_guardian.ps1) | PowerShell | Запускает AnythingLLM, затем `bot.py` через venv |
| [`farm_guardian/weather_collector.py`](farm_guardian/weather_collector.py) | `python weather_collector.py` | Отдельный скрипт сбора погоды (запускается по расписанию вручную или через планировщик) |

---

## 4. Основные модули и их назначение

### Ядро бота

| Модуль | Назначение |
|---|---|
| [`bot.py`](farm_guardian/bot.py) | Инициализация Telegram Application, регистрация хэндлеров, запуск фонового монитора погоды |
| [`app_context.py`](farm_guardian/app_context.py) | Датакласс `AppContext` — единый контейнер конфигурации, путей, состояния погоды и event loop; функция `safe_display()` для экранирования путей в Telegram |
| [`config.py`](farm_guardian/config.py) | Загрузка конфигурации из `config/secrets.json` и переменных окружения; дефолтные пороги погоды |
| [`controller.py`](farm_guardian/controller.py) | Построение плана записи (`build_plan_from_text`): распознавание животных, протоколов, погодного запроса; форматирование превью; выполнение плана через `file_executor` |
| [`file_executor.py`](farm_guardian/file_executor.py) | Физическая запись данных в Markdown-файлы: создание файла по шаблону если не существует, поиск/создание секции, вставка записи с временной меткой |
| [`pending_store.py`](farm_guardian/pending_store.py) | Хранение плана записи в `storage/pending.json` до подтверждения пользователем; TTL-очистка протухших планов |
| [`protocols.py`](farm_guardian/protocols.py) | Загрузка индекса YAML-протоколов, парсинг шагов, построение текстового превью расписания процедур |

### Хэндлеры Telegram

| Модуль | Команды |
|---|---|
| [`handlers/core.py`](farm_guardian/handlers/core.py) | `/start` — приветствие + авто-подписка на погоду; `/ping` — диагностика состояния бота |
| [`handlers/farm.py`](farm_guardian/handlers/farm.py) | `/note <текст>` — запись в журнал; `/observe <Имя> <текст>` — наблюдение по животному |
| [`handlers/confirm.py`](farm_guardian/handlers/confirm.py) | `/yes` — подтвердить и выполнить план; `/no` — отменить план |
| [`handlers/weather.py`](farm_guardian/handlers/weather.py) | `/weather_on`, `/weather_off` — управление подпиской; `/weather_now` — текущая погода с диагностикой |

### Погодная подсистема

| Модуль | Назначение |
|---|---|
| [`weather/monitor.py`](farm_guardian/weather/monitor.py) | Фоновый daemon-поток: читает `weather.json` каждые N секунд, рассылает уведомления подписчикам при смене состояния; повтор alert-уведомлений в 09:00 и 19:00 (GMT+5) |
| [`weather/rules.py`](farm_guardian/weather/rules.py) | Классификация состояния погоды (`ok`/`warn`/`alert`/`stale`), форматирование сообщений, диагностика файла `weather.json` |
| [`weather/subscribers.py`](farm_guardian/weather/subscribers.py) | Чтение/запись списка подписчиков в `storage/weather_subscribers.json` |
| [`weather_collector.py`](farm_guardian/weather_collector.py) | Запрос к Open-Meteo API, вычисление минимальных температур на 12ч и 24ч вперёд, запись в `farm_memory/sensors/weather.json` |

### Вспомогательные / не интегрированные

| Модуль | Назначение |
|---|---|
| [`llm_client.py`](farm_guardian/llm_client.py) | HTTP-клиент для AnythingLLM API (`/api/v1/workspace/{slug}/chat`); в бота не интегрирован, используется как отдельный модуль |
| [`get_slug.py`](farm_guardian/get_slug.py) | Утилита: запрашивает список воркспейсов AnythingLLM и печатает их slug |
| [`weather_monitor.py`](farm_guardian/weather_monitor.py) | Старая автономная версия монитора погоды (класс `WeatherMonitor`); ботом не используется |

---

## 5. Поток данных в системе

### Запись наблюдения (`/note` или `/observe`)

```
Пользователь → /note <текст>
    → handlers/farm.py :: handle_farm_request()
        → controller.py :: build_plan_from_text()
            → extract_animal_slugs()   # поиск животных по псевдонимам из animals.json
            → extract_protocol_name()  # поиск строки "Протокол: ..."
            → protocols.py :: load_protocols_index() + build_steps_preview()  # если протокол найден
            → wants_weather() + format_weather_brief()  # если запрошена погода
        → pending_store.py :: set_plan()  # сохранить план в storage/pending.json
    → Telegram: показать превью плана
        → Пользователь: /yes или /no
            /yes → handlers/confirm.py :: yes()
                → controller.py :: execute_action()
                    → file_executor.py :: execute()  # запись в .md файлы
                → pending_store.py :: clear_plan()
            /no → pending_store.py :: clear_plan()
```

### Погодные уведомления (фоновый поток)

```
weather_collector.py (внешний скрипт, по расписанию)
    → Open-Meteo API
    → farm_memory/sensors/weather.json

weather/monitor.py (daemon-поток, запускается при старте бота)
    → читает weather.json каждые N секунд
    → weather/rules.py :: classify_weather()
    → при смене состояния или по расписанию (09:00/19:00):
        → weather/subscribers.py :: load_weather_subscribers()
        → app.bot.send_message() для каждого подписчика
```

---

## 6. Внешние интеграции

| Сервис | Модуль | Описание |
|---|---|---|
| **Telegram Bot API** | [`bot.py`](farm_guardian/bot.py), все хэндлеры | Основной интерфейс взаимодействия с пользователем; библиотека `python-telegram-bot` |
| **Open-Meteo API** | [`weather_collector.py`](farm_guardian/weather_collector.py) | Бесплатный погодный API; запрос почасовой температуры на 2 дня вперёд; координаты: lat=55.44, lon=65.34 |
| **AnythingLLM** | [`llm_client.py`](farm_guardian/llm_client.py) | Локальный LLM-сервер (`http://localhost:3001`); клиент реализован, но в бота не интегрирован |

---

## 7. Хранилища данных

### Runtime-хранилища (создаются автоматически)

| Файл | Формат | Содержимое |
|---|---|---|
| [`farm_guardian/storage/pending.json`](farm_guardian/storage/pending.json) | JSON | Планы записи, ожидающие подтверждения `/yes`; ключ — `chat_id`, значение — план + timestamp; TTL по умолчанию 900 сек |
| [`farm_guardian/storage/weather_subscribers.json`](farm_guardian/storage/weather_subscribers.json) | JSON | Список `chat_id` подписчиков погодных уведомлений |
| [`farm_guardian/farm_memory/sensors/weather.json`](farm_guardian/farm_memory/sensors/weather.json) | JSON | Последние данные погоды: `ts`, `t_min_next_12h`, `t_min_next_24h`, `source`, `lat`, `lon` |

### Память фермы (Markdown)

| Путь | Формат | Содержимое |
|---|---|---|
| `farm_memory/resources/journal/YYYY-MM/YYYY-MM-DD.md` | Markdown | Дневные журналы; секция `## Записи`; создаются автоматически при первой записи |
| `farm_memory/resources/animals/{slug}.md` | Markdown | Карточки животных; секция `## Хроника`; создаются автоматически |
| `farm_memory/resources/feed.md` | Markdown | Учёт кормов; секции `## Текущие запасы` и `## Лог` |

### Справочные данные (статические)

| Путь | Формат | Содержимое |
|---|---|---|
| `farm_memory/resources/animals.json` | JSON | Словарь псевдонимов животных: `{slug: [список_имён]}` |
| `farm_memory/protocols/**/*.yaml` | YAML | Ветеринарные протоколы: поля `name`, `species`, `steps[]` (day, title, critical, note, medical_ref) |
| `farm_memory/medical_reference/**/*.md` | Markdown | Справочные описания к шагам протоколов |
| `farm_memory/system/animal_template.md` | Markdown | Шаблон карточки животного |
| `farm_memory/system/journal_template.md` | Markdown | Шаблон дневного журнала |

### Конфигурация

| Файл | Формат | Содержимое |
|---|---|---|
| `farm_guardian/config/secrets.json` | JSON | `TELEGRAM_TOKEN`, опционально: `WEATHER_CHECK_EVERY_SEC`, `WEATHER_STALE_HOURS`, `WEATHER_WARN_T12`, `WEATHER_ALERT_T12`, `PENDING_TTL_SECONDS` |

---

## 8. Что уже работает

- **Telegram-бот** запускается через `bot.py`, регистрирует 9 команд в меню бота.
- **`/start`** — приветственное сообщение со списком команд; автоматическая подписка чата на погодные уведомления.
- **`/ping`** — диагностическое сообщение: путь к secrets, TTL, количество подписчиков, состояние погоды.
- **`/note <текст>`** — создание плана записи в журнал с превью и ожиданием подтверждения.
- **`/observe <Имя> <текст>`** — создание плана записи в журнал + карточку животного.
- **Распознавание животных** по псевдонимам из `animals.json` (5 животных: masha, plusha, iriska, stella, fedor) с нормализацией текста (регистр, ё→е, пунктуация).
- **`/yes`** — выполнение плана: физическая запись в Markdown-файлы с временной меткой; автосоздание файла по шаблону если не существует.
- **`/no`** — отмена плана.
- **TTL-очистка** ожидающих планов (по умолчанию 15 минут).
- **Протоколы**: при наличии строки `Протокол: <название>` в тексте — поиск по индексу YAML-файлов и вывод расписания шагов в превью. Реализованы протоколы для телят (0–2 мес, 2–12 мес), КРС (сухостой, новотельный период), свиноматок (беременность, лактация, восстановление).
- **`/weather_now`** — текущая погода с классификацией (ok/warn/alert/stale) и диагностикой файла при stale.
- **`/weather_on` / `/weather_off`** — управление подпиской на автоуведомления.
- **Фоновый монитор погоды**: daemon-поток проверяет `weather.json` каждые 5 минут (настраиваемо); рассылает уведомления при смене состояния; повторяет alert-уведомления в 09:00 и 19:00 (GMT+5).
- **Сборщик погоды** (`weather_collector.py`): запрашивает Open-Meteo, вычисляет `t_min_next_12h` и `t_min_next_24h`, записывает в `weather.json`.
- **Пороги погоды**: warn ≤ −12°C, alert ≤ −18°C (настраиваемы через конфиг); при alert — чек-лист действий.
- **Экранирование путей** в Telegram-сообщениях (`safe_display`): предотвращает распознавание путей как URL.

---

## 9. Ограничения текущей реализации

- **AnythingLLM не интегрирован в бота**: `llm_client.py` реализован и работоспособен как отдельный модуль, но ни один хэндлер бота его не вызывает. Бот работает без LLM.
- **Сборщик погоды запускается вручную**: `weather_collector.py` — отдельный скрипт без встроенного планировщика. Расписание запуска (например, через Windows Task Scheduler) настраивается вне проекта.
- **`weather_monitor.py` в корне `farm_guardian/`** — старая автономная версия монитора (класс `WeatherMonitor`), не используется ботом. Актуальная реализация находится в `weather/monitor.py`.
- **Только одно действие записи**: `file_executor.py` поддерживает только `action=modify` + `mode=replace_block`. Другие операции (удаление, переименование, чтение) не реализованы.
- **Координаты погоды захардкожены**: в `weather_collector.py` lat=55.44, lon=65.34 заданы как константы в коде.
- **Нет авторизации пользователей**: бот отвечает любому Telegram-пользователю, который напишет ему.
- **Один pending-план на чат**: в `pending_store.py` хранится не более одного ожидающего плана на `chat_id`; новый `/note` перезаписывает предыдущий.
- **Протоколы только в превью**: при выполнении `/yes` в Markdown-файлы записывается только исходный текст пользователя, без развёрнутого расписания протокола.
- **Дублирование логики погоды**: пороговая логика и форматирование сообщений частично дублируются между `controller.py` и `weather/rules.py`.
- **Абсолютный путь в `llm_client.py`**: путь к лог-файлу захардкожен как `C:/Users/user/OneDrive/Рабочий стол/Ферма/farm_guardian/farm_guardian.log`.
- **Папка `farm_memory/animals/`** содержит карточки животных в старом формате (с экранированными `\#`); активный формат — `farm_memory/resources/animals/`.
