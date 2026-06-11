# Yandex Calendar Viewer

Отдельный сервис для просмотра календарей сотрудников и переговорных комнат.

## Запуск

```bash
docker compose up --build -d
```

Открыть: [http://localhost:8083](http://localhost:8083)

## Интерфейс

![Calendar weekly view](docs/calendar-view.png)

Первый вход без SSO:

```env
APP_USERNAME=admin
APP_PASSWORD=change-me
PASSWORD_LOGIN_ENABLED=true
SSO_ENABLED=false
```

После входа откройте `/admin` и настройте allow list. Перед продуктивным запуском смените `APP_PASSWORD` или включите SSO и отключите парольный вход:

```env
SSO_ENABLED=true
PASSWORD_LOGIN_ENABLED=false
```

SSO-пользователи должны быть добавлены в allow list на странице `/admin`. Парольный вход через `APP_USERNAME` / `APP_PASSWORD` по умолчанию включен только без SSO. При `SSO_ENABLED=true` он выключен, если явно не задано `PASSWORD_LOGIN_ENABLED=true`.

Закрытые маршруты:

- `/api/calendar/events` требует авторизованную сессию и проверяет allow list для обычных пользователей.
- `/admin` и `/api/admin/*` требуют роль `admin`.
- Без входа доступны только `/login`, `/sso/login`, `/sso/callback`, `/logout`, `/health` и статические файлы.

Для Postgres можно задать один URL:

```env
DATABASE_URL=postgresql://user:password@host:5432/database
```

Также поддерживается нижний регистр `database_url`. Если URL не задан, приложение собирает подключение из `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.

Проверка:

```bash
docker compose run --rm web pytest -q
docker compose logs -f web
docker compose down
```

## API

- `GET /api/calendar/events?email=...&from_date=YYYY-MM-DD&to_date=YYYY-MM-DD&time_zone=Asia/Yekaterinburg`
- `GET /api/admin/access-users`
- `POST /api/admin/access-users`
- `PATCH /api/admin/access-users/{id}`
- `DELETE /api/admin/access-users/{id}`

К Yandex Calendar API сервис обращается через `/v1/calendar/events` с параметрами `from` и `to` в формате ISO 8601 `YYYY-MM-DDTHH:MM:SSZ`.
Если у вас нет доступа в API календаря - обратитесь в поддержку яндекс 360 для бизнеса. 
