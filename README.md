# GigaAM Dictation

macOS menu bar приложение для диктовки на русском языке с использованием модели GigaAM-v3 от Сбера.

## Возможности

- Горячая клавиша для старта/стопа записи (по умолчанию Cmd+Shift+D, настраивается)
- Распознавание русской речи с пунктуацией и нормализацией текста
- Автовставка текста в место курсора
- Сохранение всех надиктовок на диск
- Выбор микрофона
- Автозапуск при входе в систему
- Визуальный индикатор записи в menu bar

## Требования

- macOS (Apple Silicon / Intel)
- Python 3.10+ (через conda)
- ffmpeg
- HuggingFace токен (для аудио длиннее 25 секунд)

## Установка

### Быстрая установка

```bash
chmod +x setup.sh
./setup.sh
```

### Ручная установка

```bash
# 1. Создать окружение
conda create -n dictation python=3.11 -y
conda activate dictation

# 2. Установить GigaAM
cd ../GigaAM
pip install -e .
pip install -e ".[longform]"

# 3. Установить зависимости приложения
pip install rumps pynput sounddevice python-dotenv pyobjc-framework-Cocoa

# 4. Создать .env файл
echo "HF_TOKEN=hf_your_token_here" > .env
```

### HuggingFace токен

Для распознавания аудио длиннее 25 секунд нужен HuggingFace токен:

1. Зайди на https://huggingface.co/pyannote/segmentation-3.0 и нажми "Agree"
2. Создай токен на https://huggingface.co/settings/tokens (тип: Read)
3. Добавь в `.env`: `HF_TOKEN=hf_xxx`

## Использование

```bash
conda activate dictation
cd dictation-app
python app.py
```

### Как пользоваться

1. Запусти приложение — иконка микрофона появится в menu bar
2. Нажми **Cmd+Shift+D** — начнётся запись (иконка станет красной)
3. Говори по-русски
4. Нажми **Cmd+Shift+D** снова — запись остановится, начнётся распознавание (иконка жёлтая)
5. Через несколько секунд текст вставится туда, где стоит курсор
6. Текст также сохранится в папке `dictations/`

### Меню приложения

- **Start/Stop Dictation** — ручное управление записью
- **Microphone** — выбор микрофона
- **Auto-paste** — включить/выключить автовставку
- **Open Dictations Folder** — открыть папку с надиктовками
- **Start on Login** — автозапуск при входе в систему

## Модель

Используется **GigaAM-v3 (e2e_rnnt)** — лучшая версия для распознавания русской речи:
- ~240M параметров, ~500MB на диске
- Обучена на 700K часов русской речи
- Пунктуация и нормализация текста из коробки
- Работает на CPU (GPU не нужен)
- На M4 распознаёт 5 минут аудио за ~10-20 секунд

## Разрешения macOS

При первом запуске macOS попросит:
- **Accessibility** — для глобальной горячей клавиши (System Settings → Privacy & Security → Accessibility)
- **Microphone** — для записи аудио (появится автоматически)

## Структура проекта

```
dictation-app/
├── app.py              # Точка входа
├── .env                # HF_TOKEN
├── config/settings.json # Настройки
├── core/
│   ├── recorder.py     # Запись аудио
│   ├── transcriber.py  # GigaAM распознавание
│   └── clipboard.py    # Буфер обмена + автовставка
├── ui/
│   ├── menubar.py      # Menu bar приложение
│   ├── hotkey.py       # Горячие клавиши
│   └── indicator.py    # Плавающий индикатор
├── utils/
│   ├── config.py       # Настройки
│   ├── autostart.py    # Автозапуск
│   └── audio_utils.py  # Утилиты для аудио
└── dictations/         # Сохранённые надиктовки
```
