# Dockerfile

# --- STAGE 1: Сборщик (Builder) ---
# Используем полную версию Python для установки зависимостей,
# так как могут понадобиться инструменты для сборки некоторых пакетов.
FROM python:3.12-slim as builder

# Устанавливаем рабочую директорию
WORKDIR /app

# Создаем виртуальное окружение. Это хорошая практика,
# чтобы не засорять системный Python и уменьшить размер итогового образа.
ENV VIRTUAL_ENV=/app/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Копируем только файл с зависимостями для кэширования этого слоя
COPY requirements.txt .

# Устанавливаем зависимости в виртуальное окружение
RUN pip install --no-cache-dir -r requirements.txt


# --- STAGE 2: Финальный образ (Final Image) ---
# Используем тот же легковесный образ, что и для сборщика.
FROM python:3.12-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем уже созданное виртуальное окружение из сборщика
COPY --from=builder /app/venv /app/venv

# Копируем весь код нашего бота
COPY . .

# Указываем Python, что нужно использовать интерпретатор из нашего venv
ENV PATH="/app/venv/bin:$PATH"

# Команда для запуска бота при старте контейнера
CMD ["python", "-m", "bot.main"]