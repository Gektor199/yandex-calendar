from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.calendar_client import CalendarClient, CalendarClientError, date_chunks, yandex_datetime_boundary
from app.config import Settings
from app.event_normalizer import normalize_events
from app.main import create_app
from app.sso import SSOProfile


class FakeCalendarClient:
    def __init__(self):
        self.calls = 0

    async def events_for_user(self, email: str, from_date: date, to_date: date, time_zone: str) -> list[dict]:
        self.calls += 1
        if email == "error@example.com":
            raise CalendarClientError("OAuth вернул HTTP 403")
        return [
            {
                "event_id": "event-1",
                "summary": "Планирование",
                "start": {"date_time": f"{from_date.isoformat()}T10:00:00", "time_zone": time_zone},
                "end": {"date_time": f"{from_date.isoformat()}T11:30:00", "time_zone": time_zone},
                "location": "Переговорная 1",
                "participants": [
                    {"name": "Ольга Куликова", "status": "accepted"},
                    {"email": "ivan@example.com", "status": "declined"},
                    {"name": "Без статуса"},
                ],
            }
        ]


class FakeDatabase:
    def __init__(self):
        self.items = []
        self.next_id = 1

    def initialize(self):
        return None

    def list_access_users(self):
        return [dict(item, allowed_calendars=list(item["allowed_calendars"])) for item in self.items]

    def get_access_user_by_email(self, email: str):
        clean_email = email.strip().lower()
        for item in self.items:
            if item["email"] == clean_email:
                return dict(item, allowed_calendars=list(item["allowed_calendars"]))
        return None

    def update_access_user_name(self, email: str, full_name: str):
        user = self.get_access_user_by_email(email)
        if not user:
            return
        for item in self.items:
            if item["id"] == user["id"]:
                item["full_name"] = full_name

    def add_access_user(self, email: str, role: str, allow_all: bool, allowed_calendars: list[str]):
        clean_email = email.strip().lower()
        if self.get_access_user_by_email(clean_email):
            from app.database import DuplicateEmailError

            raise DuplicateEmailError(clean_email)
        self.items.append(
            {
                "id": self.next_id,
                "email": clean_email,
                "full_name": "",
                "role": role,
                "allow_all": allow_all,
                "allowed_calendars": list(allowed_calendars),
                "created_at": "2026-06-10T00:00:00+00:00",
                "updated_at": "2026-06-10T00:00:00+00:00",
            }
        )
        self.next_id += 1

    def update_access_user(self, access_user_id: int, email: str, role: str, allow_all: bool, allowed_calendars: list[str]):
        clean_email = email.strip().lower()
        if any(item["id"] != access_user_id and item["email"] == clean_email for item in self.items):
            from app.database import DuplicateEmailError

            raise DuplicateEmailError(clean_email)
        for item in self.items:
            if item["id"] == access_user_id:
                item["email"] = clean_email
                item["role"] = role
                item["allow_all"] = allow_all
                item["allowed_calendars"] = list(allowed_calendars)
                return True
        return False

    def delete_access_user(self, access_user_id: int):
        before = len(self.items)
        self.items = [item for item in self.items if item["id"] != access_user_id]
        return len(self.items) != before

    def user_can_access_calendar(self, user_email: str, calendar_email: str):
        user = self.get_access_user_by_email(user_email)
        if not user:
            return False
        return user["role"] == "admin" or user["allow_all"] or calendar_email.strip().lower() in user["allowed_calendars"]


class FakeSSOClient:
    def __init__(self, email: str):
        self.email = email

    async def profile_from_code(self, *, code: str, redirect_uri: str, code_verifier: str = "") -> SSOProfile:
        return SSOProfile(email=self.email, name=self.email)


def settings_for(tmp_path) -> Settings:
    return Settings(
        app_name="Calendar Viewer Test",
        secret_key="test-secret",
        app_username="admin",
        app_password="password",
        password_login_enabled=True,
        database_url="postgresql://test:test@db/test",
        yandex_client_id="client",
        yandex_client_secret="secret",
        oauth_url="https://oauth.invalid/token",
        calendar_api_base="https://calendar.invalid/v1/calendar",
        default_time_zone="Asia/Yekaterinburg",
        max_calendar_days=31,
        request_timeout=2,
        sso_enabled=False,
        sso_provider_name="Test SSO",
        sso_authorization_url="https://sso.invalid/auth",
        sso_token_url="https://sso.invalid/token",
        sso_userinfo_url="https://sso.invalid/userinfo",
        sso_client_id="sso-client",
        sso_client_secret="sso-secret",
        sso_client_auth_method="post",
        sso_redirect_uri="http://testserver/sso/callback",
        sso_scopes="openid email profile",
    )


def test_settings_accept_database_url_aliases(tmp_path, monkeypatch):
    for key in ["DATABASE_URL", "database_url", "POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]:
        monkeypatch.delenv(key, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("database_url=postgres://u:p@db:5432/app\n")

    settings = Settings.from_environment(env_file)

    assert settings.database_url == "postgresql://u:p@db:5432/app"


def test_env_example_allows_bootstrap_password_login(monkeypatch):
    for key in ["SSO_ENABLED", "PASSWORD_LOGIN_ENABLED"]:
        monkeypatch.delenv(key, raising=False)

    settings = Settings.from_environment(Path(__file__).resolve().parents[1] / ".env.example")

    assert settings.sso_enabled is False
    assert settings.password_login_enabled is True


def test_date_chunks_respect_seven_calendar_days():
    assert date_chunks(date(2026, 6, 1), date(2026, 6, 15)) == [
        (date(2026, 6, 1), date(2026, 6, 7)),
        (date(2026, 6, 8), date(2026, 6, 14)),
        (date(2026, 6, 15), date(2026, 6, 15)),
    ]


def test_yandex_datetime_boundary_uses_iso_utc():
    assert yandex_datetime_boundary(date(2026, 6, 1), end_of_day=False) == "2026-06-01T00:00:00Z"
    assert yandex_datetime_boundary(date(2026, 6, 7), end_of_day=True) == "2026-06-07T23:59:59Z"


def test_calendar_client_loads_event_participants(tmp_path):
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.host == "oauth.invalid":
            return httpx.Response(200, json={"access_token": "user-token"})
        if str(request.url).endswith("/participants"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"email": "one@example.com", "decision": "ACCEPTED"},
                        {"email": "two@example.com", "decision": "DECLINED"},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "event_id": "event-1",
                        "summary": "Встреча",
                        "start": {"date_time": "2026-06-02T11:00:00"},
                        "end": {"date_time": "2026-06-02T12:00:00"},
                    }
                ]
            },
        )

    async def run_request():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await CalendarClient(settings_for(tmp_path), http_client).events_for_user(
                "one@example.com", date(2026, 6, 1), date(2026, 6, 1), "Asia/Yekaterinburg"
            )

    events = asyncio.run(run_request())
    assert events[0]["participants"][0]["decision"] == "ACCEPTED"
    assert any("/events/event-1/participants" in url for url in requests)
    event_requests = [url for url in requests if "/events?" in url]
    assert "from=2026-06-01T00%3A00%3A00Z" in event_requests[0]
    assert "to=2026-06-01T23%3A59%3A59Z" in event_requests[0]
    assert "from_date" not in event_requests[0]
    assert "to_date" not in event_requests[0]


def test_calendar_client_paginates_events_with_iteration_key(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "oauth.invalid":
            return httpx.Response(200, json={"access_token": "user-token"})
        if str(request.url).endswith("/participants"):
            return httpx.Response(200, json={"items": []})
        if request.url.params.get("iteration_key") == "next-page":
            return httpx.Response(
                200,
                json={
                    "limit": 10,
                    "items": [
                        {
                            "event_id": "event-2",
                            "summary": "Вторая страница",
                            "start": {"date_time": "2026-06-02T12:00:00"},
                            "end": {"date_time": "2026-06-02T13:00:00"},
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "limit": 10,
                "iteration_key": "next-page",
                "items": [
                    {
                        "event_id": "event-1",
                        "summary": "Первая страница",
                        "start": {"date_time": "2026-06-02T11:00:00"},
                        "end": {"date_time": "2026-06-02T12:00:00"},
                    }
                ],
            },
        )

    async def run_request():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            return await CalendarClient(settings_for(tmp_path), http_client).events_for_user(
                "one@example.com", date(2026, 6, 1), date(2026, 6, 1), "Asia/Yekaterinburg"
            )

    events = asyncio.run(run_request())
    assert [event["summary"] for event in events] == ["Первая страница", "Вторая страница"]
    assert any(request.url.params.get("iteration_key") == "next-page" for request in requests)


def test_normalize_events_for_calendar_grid():
    events = normalize_events(
        [
            {
                "event_id": "1",
                "summary": "Встреча",
                "start": {"date_time": "2026-06-02T11:00:00", "time_zone": "Asia/Yekaterinburg"},
                "end": {"date_time": "2026-06-02T13:00:00", "time_zone": "Asia/Yekaterinburg"},
            }
        ],
        "Asia/Yekaterinburg",
    )
    assert events[0]["title"] == "Встреча"
    assert events[0]["day"] == "2026-06-02"
    assert events[0]["start_minutes"] == 660
    assert events[0]["end_minutes"] == 780


def test_normalize_events_keeps_participants_and_statuses():
    events = normalize_events(
        [
            {
                "event_id": "1",
                "summary": "Встреча",
                "start": {"date_time": "2026-06-02T11:00:00", "time_zone": "Asia/Yekaterinburg"},
                "end": {"date_time": "2026-06-02T12:00:00", "time_zone": "Asia/Yekaterinburg"},
                "participants": [
                    {"name": "Ольга", "status": "accepted"},
                    {"email": "ivan@example.com", "responseStatus": "declined"},
                    {"displayName": "Анна"},
                ],
            }
        ],
        "Asia/Yekaterinburg",
    )
    assert events[0]["participants"] == [
        {"name": "Ольга", "email": "", "status": "придет"},
        {"name": "ivan@example.com", "email": "ivan@example.com", "status": "не придет"},
        {"name": "Анна", "email": "", "status": ""},
    ]


def test_calendar_events(tmp_path):
    app = create_app(settings_for(tmp_path), database=FakeDatabase())
    app.state.calendar_client_factory = lambda _: FakeCalendarClient()

    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        client.post("/login", data={"username": "admin", "password": "password"})
        response = client.get(
            "/api/calendar/events",
            params={
                "email": "ONE@EXAMPLE.COM",
                "from_date": "2026-06-01",
                "to_date": "2026-06-05",
                "time_zone": "Asia/Yekaterinburg",
            },
        )
        assert response.status_code == 200
        assert response.json()["email"] == "one@example.com"
        assert response.json()["items"][0]["title"] == "Планирование"
        assert response.json()["items"][0]["participants"][0]["status"] == "придет"

def test_calendar_api_errors_are_reported(tmp_path):
    app = create_app(settings_for(tmp_path), database=FakeDatabase())
    app.state.calendar_client_factory = lambda _: FakeCalendarClient()

    with TestClient(app) as client:
        client.post("/login", data={"username": "admin", "password": "password"})
        response = client.get(
            "/api/calendar/events",
            params={
                "email": "error@example.com",
                "from_date": "2026-06-01",
                "to_date": "2026-06-05",
                "time_zone": "Asia/Yekaterinburg",
            },
        )
        assert response.status_code == 502
        assert "OAuth вернул HTTP 403" in response.json()["detail"]


def test_calendar_events_use_cache_and_error_backoff(tmp_path):
    app = create_app(settings_for(tmp_path), database=FakeDatabase())
    fake = FakeCalendarClient()
    app.state.calendar_client_factory = lambda _: fake
    params = {
        "email": "one@example.com",
        "from_date": "2026-06-01",
        "to_date": "2026-06-05",
        "time_zone": "Asia/Yekaterinburg",
    }

    with TestClient(app) as client:
        client.post("/login", data={"username": "admin", "password": "password"})
        first = client.get("/api/calendar/events", params=params)
        second = client.get("/api/calendar/events", params=params)
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["cached"] is True
        assert fake.calls == 1
        refreshed = client.get("/api/calendar/events", params={**params, "refresh": "true"})
        assert refreshed.status_code == 200
        assert fake.calls == 2

        error_params = {**params, "email": "error@example.com"}
        assert client.get("/api/calendar/events", params=error_params).status_code == 502
        assert client.get("/api/calendar/events", params=error_params).status_code == 502
        assert fake.calls == 3


def test_sso_login_button_and_callback_allow_list(tmp_path):
    database = FakeDatabase()
    database.add_access_user("allowed@example.com", "user", False, ["one@example.com"])
    settings = Settings(**{**settings_for(tmp_path).__dict__, "sso_enabled": True, "password_login_enabled": False})
    app = create_app(settings, database=database)

    with TestClient(app) as client:
        page = client.get("/login")
        assert "Войти через Test SSO" in page.text
        assert 'name="password"' not in page.text
        local_login = client.post("/login", data={"username": "admin", "password": "password"})
        assert local_login.status_code == 403
        redirect = client.get("/sso/login", follow_redirects=False)
        assert redirect.status_code == 303
        assert redirect.headers["location"].startswith("https://sso.invalid/auth?")
        state = client.cookies.get("session")
        assert state
        # Pull the stored state by starting a new login and reading the session through callback URL built by app.
        login_redirect = client.get("/sso/login", follow_redirects=False)
        location = login_redirect.headers["location"]
        import urllib.parse

        query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
        app.state.sso_client_factory = lambda _: FakeSSOClient("allowed@example.com")
        callback = client.get(f"/sso/callback?code=test-code&state={query['state'][0]}", follow_redirects=False)
        assert callback.status_code == 303


def test_admin_can_manage_allow_list(tmp_path):
    app = create_app(settings_for(tmp_path), database=FakeDatabase())

    with TestClient(app) as client:
        client.post("/login", data={"username": "admin", "password": "password"})
        assert client.get("/admin").status_code == 200
        created = client.post(
            "/api/admin/access-users",
            json={
                "email": "domain.user",
                "role": "user",
                "allow_all": False,
                "allowed_calendars": ["one@example.com", "two@example.com"],
            },
        )
        assert created.status_code == 200
        user = created.json()["items"][0]
        assert user["email"] == "domain.user"
        assert user["allowed_calendars"] == ["one@example.com", "two@example.com"]
        updated = client.patch(
            f"/api/admin/access-users/{user['id']}",
            json={"email": "renamed.user", "role": "admin", "allow_all": True, "allowed_calendars": []},
        )
        assert updated.status_code == 200
        assert updated.json()["items"][0]["email"] == "renamed.user"
        assert updated.json()["items"][0]["allow_all"] is True
        assert client.delete(f"/api/admin/access-users/{user['id']}").status_code == 200


def test_api_requires_login(tmp_path):
    app = create_app(settings_for(tmp_path), database=FakeDatabase())

    with TestClient(app) as client:
        calendar = client.get(
            "/api/calendar/events",
            params={
                "email": "allowed@example.com",
                "from_date": "2026-06-01",
                "to_date": "2026-06-05",
                "time_zone": "Asia/Yekaterinburg",
            },
        )
        assert calendar.status_code == 401
        assert client.get("/api/me").status_code == 401
        assert client.get("/api/admin/access-users").status_code == 401


def test_sso_user_can_read_only_allowed_calendars(tmp_path):
    database = FakeDatabase()
    database.add_access_user("viewer@example.com", "user", False, ["allowed@example.com"])
    settings = Settings(**{**settings_for(tmp_path).__dict__, "sso_enabled": True, "password_login_enabled": False})
    app = create_app(settings, database=database)
    app.state.calendar_client_factory = lambda _: FakeCalendarClient()

    with TestClient(app) as client:
        login_redirect = client.get("/sso/login", follow_redirects=False)
        import urllib.parse

        query = urllib.parse.parse_qs(urllib.parse.urlparse(login_redirect.headers["location"]).query)
        app.state.sso_client_factory = lambda _: FakeSSOClient("viewer@example.com")
        client.get(f"/sso/callback?code=test-code&state={query['state'][0]}", follow_redirects=False)
        allowed = client.get(
            "/api/calendar/events",
            params={
                "email": "allowed@example.com",
                "from_date": "2026-06-01",
                "to_date": "2026-06-05",
                "time_zone": "Asia/Yekaterinburg",
            },
        )
        denied = client.get(
            "/api/calendar/events",
            params={
                "email": "denied@example.com",
                "from_date": "2026-06-01",
                "to_date": "2026-06-05",
                "time_zone": "Asia/Yekaterinburg",
            },
        )
        assert allowed.status_code == 200
        assert denied.status_code == 403
