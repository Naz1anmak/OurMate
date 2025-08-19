# OurMate Bot

**Telegram‑бот с интеграцией LLM и планировщиком поздравлений**

---

## 📖 Описание

OurMate — это умный Telegram‑бот на базе [aiogram](https://docs.aiogram.dev/) и внешней LLM.

Он умеет:
- Отвечать на упоминания и личные сообщения с контекстом предыдущих диалогов
- Ежедневно в заданное время проверять JSON-файл с днями рождения и **поздравлять в группе**
- При запуске бота **уведомлять владельца в личку** о ближайшем дне рождения
- Предоставлять **владельцу специальные команды** для управления сервером

📺 Для первоначальной настройки LLM и получения API использован сервис _io.net_ — пример развертывания показан в видео: https://youtu.be/5BgVrPteZbQ

---

## ⚙️ Главные фишки

### 1. **Интерактивный чат**
- Обрабатывает упоминания и личные сообщения
- Запоминает предыдущий вопрос–ответ, не путая контексты разных пользователей
- Использует внешнюю LLM для генерации ответов

### 2. **Планировщик поздравлений**
- Читает `data/birthdays.json` и каждый день в заданное время шлёт поздравление в беседу (только если сегодня есть именинники); после поздравление пишет владельцу, кто следующий именинник
- Поздравляет именинников по шаблону из `.env`
- При запуске бота присылает владельцу уведомление о ближайшем дне рождения

### 3. **Команды владельца**
Список команд приведён в разделе «Команды владельца» ниже.

### 4. **Гибкая конфигурация через `.env`**
- Все токены и ключи хранятся в одном файле
- Промпты для чата и поздравлений можно менять без правки кода

---

## 📁 Структура проекта

```
OurMate_bot/
├── src/                          # Основной код приложения
│   ├── bot/                      # Логика Telegram бота
│   │   ├── handlers/             # Обработчики сообщений
│   │   │   ├── chat.py           # Обработка обычных сообщений
│   │   │   ├── commands.py       # Обработка команд (/start)
│   │   │   └── owner_commands.py # Команды владельца
│   │   ├── services/             # Бизнес-логика
│   │   │   ├── llm_service.py    # Работа с LLM API
│   │   │   ├── birthday_service.py # Логика дней рождения
│   │   │   ├── context_service.py  # Управление контекстом
│   │   │   └── system_service.py   # Системные команды
│   │   └── scheduler/            # Планировщик задач
│   │       └── birthday_scheduler.py # Планировщик поздравлений
│   ├── models/                   # Модели данных
│   │   └── user.py               # Модель пользователя
│   ├── utils/                    # Вспомогательные функции
│   │   ├── date_utils.py         # Работа с датами
│   │   └── text_utils.py         # Работа с текстом
│   └── config/                   # Конфигурация
│       └── settings.py           # Настройки приложения
├── data/                         # Данные приложения
│   └── birthdays.json            # Файл с днями рождения
├── main.py                       # Точка входа
├── requirements.txt              # Зависимости Python
├── .env                          # Переменные окружения
└── README.md                     # Документация
```

---

## 🚀 Установка и запуск

### 1. **Клонировать репозиторий**
```bash
git clone https://github.com/Naz1anmak/OurMate.git
cd OurMate
```

### 2. **Создать и активировать виртуальное окружение**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. **Настроить `.env`**

В корне проекта создайте файл `.env` и добавьте (замените на свои значения):

```ini
# Telegram настройки
BOT_TOKEN=123456789:AA…            # токен вашего Telegram-бота
OWNER_CHAT_ID=987654321            # ваш личный chat_id
CHAT_ID=-1001234567890             # chat_id группы для поздравлений

# LLM API настройки
MODEL=deepseek-ai/DeepSeek-R1-0528
LLM_API_KEY=io-v2-…                # ключ LLM API

# Настройки дней рождения
BIRTHDAYS_FILE=data/birthdays.json

# Настройки расписания
TIMEZONE=Europe/Moscow             # время для проверки и отправки поздравлений
SEND_HOUR=10
SEND_MINUTE=0

# Промпты
PROMPT_TEMPLATE_CHAT='Ты — бот, отвечающий…'               # промпт для ответов в лс и беседе
PROMPT_TEMPLATE_BIRTHDAY='Поздравь студентов {mentions}…'  # промпт для генерации поздравлений
```

### 4. **Пример `data/birthdays.json`**
```json
{
    "users": [
        {
            "user_login": "@firstLogin",
            "name": "Анастасия Ильинична",
            "birthday": "12-30"
        },
        {
            "user_login": "",
            "name": "Иван Петров",
            "birthday": "07-10"
        }
    ]
}
```

### 5. **Запуск бота**
```bash
source venv/bin/activate
python main.py
```

---

## 🔧 Команды владельца

Доступны только владельцу (проверка по `OWNER_CHAT_ID`). Можно использовать в личных сообщениях или в группе:

| Команда | Где работает | Описание |
|---------|--------------|----------|
| `logs` | ЛС/Группа | Логи бота (PM, GR, FP) |
| `full logs` | ЛС/Группа | Полные логи бота |
| `status` | ЛС/Группа | Статус службы бота |
| `system` | ЛС/Группа | Информация о системе |
| `stop bot` | ЛС/Группа | Остановить бота |
| `help` / `команды` | ЛС/Группа | Справка по командам |

---

## 💬 Публичные команды (для всех)

Доступны всем участникам в беседе; для владельца работают также в личных сообщениях с ботом:

- `др` — показать ближайший день рождения
- `др @username` — показать дату дня рождения указанного пользователя

* Нужно упомянуть бота перед командой

---

## 📋 Типы логов

- **PM** - Personal Message (личные сообщения)
- **GR** - Group Reply (ответы в группе)
- **FP** - First Ping (команды `/start`)

---

## 🧾 Работа с логами (форматирование)

- В ответах на `full logs` строки с маркерами `PM;`, `GR;`, `FP;` выделяются полужирным
- В `logs` вывод без выделения (монопространство), но с той же обрезкой с конца
- Длинные ответы безопасно обрезаются с конца (показывается самый свежий фрагмент) с отметкой о truncation
- В системных командах используется `--no-pager`, чтобы исключить управляющие последовательности из вывода

---

## 🛡️ Безопасность

- Команды владельца работают только для указанного `OWNER_CHAT_ID`
- Таймаут 30 секунд на системные команды
- Ограничение длины ответов (4000 символов)
- Проверка типов чатов (личные сообщения для команд владельца)

---

## 🔄 Развертывание на сервере

### Установка и systemd-сервис (кратко)

1. Обновите систему и установите зависимости:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git
```

2. Клонируйте репозиторий и подготовьте окружение:
```bash
git clone https://github.com/Naz1anmak/OurMate.git bot && cd bot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

3. Создайте .env со своими значениями (BOT_TOKEN, OWNER_CHAT_ID, CHAT_ID, MODEL, LLM_API_KEY, BIRTHDAYS_FILE, TIMEZONE, SEND_HOUR, SEND_MINUTE, PROMPT_TEMPLATE_*).

4. Создайте файл `/etc/systemd/system/mybot.service`:
```ini
[Unit]
Description=OurMate Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/bot
EnvironmentFile=/root/bot/.env
ExecStart=/root/bot/venv/bin/python -u main.py
StandardOutput=journal
StandardError=journal
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

5. Активируйте и запустите службу:
```bash
sudo systemctl daemon-reload
sudo systemctl enable mybot
sudo systemctl start mybot
```

6. Проверьте статус:
```bash
sudo systemctl status mybot
```

### (Опционально) Сделать журнал systemd постоянным

По умолчанию на некоторых системах логи `systemd-journald` могут храниться только в памяти и теряться после перезагрузки. Чтобы команды владельца `logs`/`full logs` имели доступ к истории после рестартов, включите постоянное хранение журнала:

```bash
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/00-custom.conf > /dev/null << 'EOF'
[Journal]
Storage=persistent
SystemMaxUse=100M
EOF
sudo systemctl restart systemd-journald
```

После этого `journalctl -u mybot` будет показывать историю логов между перезагрузками.

---

## 🎯 Особенности

- **Модульная архитектура** - четкое разделение ответственности
- **Type hints** - полная типизация для лучшей поддержки IDE
- **Логирование** - подробные логи всех взаимодействий
- **Контекст** - запоминание предыдущих диалогов
- **Безопасность** - проверки прав доступа для команд владельца

---