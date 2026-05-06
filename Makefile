.PHONY: up down restart build logs

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose up -d --build --force-recreate

build:
	docker compose build

logs:
	docker compose logs -f
