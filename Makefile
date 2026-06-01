.PHONY: help up down restart build logs tail sh stop ps env test test-cov

SERVICE ?= bot

help: ## Показать список целей
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

env: ## Создать .env из .env.example, если его нет
	@if [ -f .env ]; then \
		echo ".env уже существует — не трогаем"; \
	else \
		cp .env.example .env && echo "Создан .env — заполни значения"; \
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

# -v "$(PWD)":/app — монтируем живое дерево поверх образа, иначе pytest гоняет код,
# зашитый при сборке (src/ и tests/ в образе), а не текущие правки. Зависимости берутся
# из образа (они в site-packages, не в /app), код — с диска.
test: ## Прогон тестов в контейнере (на текущем коде)
	docker compose run --rm -v "$(PWD)":/app $(SERVICE) pytest tests/ -v

test-cov: ## Прогон тестов с покрытием
	docker compose run --rm -v "$(PWD)":/app $(SERVICE) pytest tests/ --cov=src --cov-report=term-missing -v
