.PHONY: help up down restart build logs tail sh stop ps env override test test-cov

SERVICE ?= bot

help: ## Показать список целей
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

env: ## Создать .env из .env.example, если его нет
	@if [ -f .env ]; then \
		echo ".env уже существует — не трогаем"; \
	else \
		cp .env.example .env && echo "Создан .env — заполни значения"; \
	fi

override: ## Создать docker-compose.override.yml из примера, если его нет (dev-маунт src/tests)
	@if [ -f docker-compose.override.yml ]; then \
		echo "docker-compose.override.yml уже существует — не трогаем"; \
	else \
		cp docker-compose.override.yml.example docker-compose.override.yml && echo "Создан docker-compose.override.yml — dev-маунт src/tests активен"; \
	fi

up: ## Запустить контейнеры в фоне
	docker compose up -d

down: ## Остановить и удалить контейнеры
	docker compose down

stop: ## Остановить контейнеры (без удаления)
	docker compose stop

restart: ## Пересобрать и перезапустить
	docker compose up -d --build --force-recreate

build: ## Только пересобрать образ
	docker compose build

logs: ## Прицепиться ко всем логам
	docker compose logs -f

tail: ## Последние 200 строк лога $(SERVICE) с follow
	docker compose logs -f --tail=200 $(SERVICE)

ps: ## Список контейнеров compose
	docker compose ps

sh: ## Зайти внутрь контейнера $(SERVICE)
	docker compose exec $(SERVICE) sh

# Живой код монтируется через docker-compose.override.yml (создаётся `make override`):
# src/ и tests/ ложатся поверх образа, иначе pytest гоняет код, зашитый при сборке,
# а не текущие правки. Зависимости берутся из образа (site-packages, не в /app).
test: override ## Прогон тестов в контейнере (на текущем коде)
	docker compose run --rm $(SERVICE) pytest tests/ -v

test-cov: override ## Прогон тестов с покрытием
	docker compose run --rm $(SERVICE) pytest tests/ --cov=src --cov-report=term-missing -v
