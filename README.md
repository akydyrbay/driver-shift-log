# driver-shift-log

Дневник смен водителя: поездки, способы оплаты и итоги выбранного дня.
FastAPI + Flutter Web + SQLite, единый Docker-образ, CI/CD в GitHub Actions.

- [backend/README.md](backend/README.md) — API, хранилище, импорт JSON.
- [frontend/README.md](frontend/README.md) — Web-клиент.

## Возможности

- Выбор дня, список поездок, сводка: число поездок, выручка, комиссия,
  «на руки», наличные и карта.
- Добавление поездки с проверкой данных, включая поездки через полночь.
- Идемпотентный `POST`: повтор с тем же ID и данными не создаёт дубль.
- SQLite с транзакциями; повторяемый импорт из JSON.
- Адаптивный интерфейс в браузере (от 360 px).

День определяется по времени **начала** поездки в `Asia/Almaty`. Суммы — целые
числа одной валюты; «на руки» = выручка − комиссия.

## Запуск в Docker

Нужны Docker с BuildKit и Docker Compose v2+.

```bash
git clone https://github.com/akydyrbay/driver-shift-log.git
cd driver-shift-log
docker compose up --build -d --wait
```

Интерфейс — http://localhost:8080, документация API — http://localhost:8080/docs.
Другой порт: `APP_PORT=8090 docker compose up --build -d --wait`.

Первый запуск создаёт пустую базу. Загрузить пример:

```bash
docker compose exec app python -m app.import_trips /app/examples/trips.json
```

Выберите `2026-10-01`: 2 поездки, выручка `3900`, комиссия `585`, «на руки» `3315`.
Свой JSON: `docker compose cp trips.json app:/tmp/trips.json`, затем импорт
`/tmp/trips.json` той же командой.

Демо-данные для скриншотов — 37 поездок с 30 сентября по 6 октября 2026
(включая пример выше, выходной 4 октября и поездку через полночь 3 октября):

```bash
docker compose exec app python -m app.import_trips /app/examples/demo_trips.json
```

Локально: `uv run --locked python -m app.import_trips data/demo_trips.json` из `backend/`.

### Данные и backup

База хранится в томе `trips-data` (`/data` в контейнере). `docker compose down`
данные сохраняет, **`docker compose down -v` удаляет их**. Backup:

```bash
docker compose stop app
docker compose cp app:/data ../shift-data-backup
docker compose start app
```

Контейнер работает от непривилегированного пользователя `10001`, с read-only
файловой системой, healthcheck на `/health` и портом только на `127.0.0.1`.

## Локальная разработка

Версии: Python `3.12.13`, uv `0.11.18`, Flutter `3.47.3`.

```bash
# Терминал 1 — API на :8000
cd backend
uv sync --locked
uv run --locked python -m app.import_trips data/trips.json   # необязательно
uv run --locked uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Терминал 2 — клиент на :8080
cd frontend
flutter pub get --enforce-lockfile
flutter run -d chrome --web-hostname localhost --web-port 8080 \
  --dart-define=API_BASE_URL=http://127.0.0.1:8000
```

| Настройка | Назначение |
| --- | --- |
| `TRIPS_DB` | Путь к SQLite; по умолчанию `backend/data/trips.sqlite3`, в Docker `/data/trips.sqlite3` |
| `WEB_DIR` | Каталог собранного клиента; если задан, backend раздаёт его на `/` |
| `API_BASE_URL` | `--dart-define` для Flutter, адрес API без `/api`; по умолчанию тот же origin |
| `APP_PORT` | Порт Compose на хосте, по умолчанию `8080` |
| `PORT` | Порт сервера внутри контейнера, по умолчанию `8000` (задаётся хостингом, например Render) |
| `SEED_FILE` | JSON для импорта при каждом запуске контейнера, например `/app/examples/demo_trips.json` |

## API

```bash
curl --fail http://localhost:8080/health
curl --fail 'http://localhost:8080/api/trips?date=2026-10-01'
curl --fail 'http://localhost:8080/api/summary?date=2026-10-01'
curl -i http://localhost:8080/api/trips \
  -H 'Content-Type: application/json' \
  -d '{"id":"demo-3","start":"2026-10-01T10:00:00+05:00","end":"2026-10-01T10:20:00+05:00","amount":2000,"payment":"cash","commission":300}'
```

`POST` возвращает `201` (создано), `200` (точный повтор), `409` (ID занят другими
данными), `422` (неверные данные), `503` (ошибка хранилища — повторите с тем же ID).
Подробности — в [backend/README.md](backend/README.md).

## Проверки

```bash
(cd backend && uv run --locked python -m unittest discover -s tests -v)
(cd frontend && flutter analyze && flutter test)
docker build --tag driver-shift-log:ci .
python3 scripts/check_container.py --image driver-shift-log:ci
```

`scripts/check_container.py` — smoke-test Docker-образа: поднимает отдельный
Compose-проект со случайным портом и временным томом, проверяет UI, API, импорт,
идемпотентность и сохранность данных после перезапуска, затем удаляет только свои
ресурсы. Нужен Python 3.10+ на хосте.

## CI/CD

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) на каждый PR и push запускает
**Backend tests**, **Flutter checks** и **Docker integration**. При push тега `v*`
проверенный образ публикуется в `ghcr.io/akydyrbay/driver-shift-log:<тег>` без
повторной сборки.

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
docker pull ghcr.io/akydyrbay/driver-shift-log:v0.1.0
```

Новый пакет GHCR может быть приватным — видимость меняется в настройках пакета.

## Ограничения

- Нет авторизации: не открывайте приложение в интернет без контроля доступа и HTTPS.
- Один хост и локальный диск; SQLite нельзя делить между серверами по сети.
- Web-клиент принимает суммы до `9007199254740991` (предел точности JavaScript),
  backend — до int64.
- Черновик формы не сохраняется после перезагрузки вкладки.
