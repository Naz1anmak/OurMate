# syntax=docker/dockerfile:1.7
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Europe/Moscow

# tzdata нужен для zoneinfo (Europe/Moscow), curl полезен для отладки
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Сначала зависимости — лучше кэшируется
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Потом код
COPY main.py ./
COPY src ./src

# Непривилегированный пользователь, владеет /app и /app/data
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /app/data \
 && chown -R app:app /app
USER app

CMD ["python", "main.py"]
