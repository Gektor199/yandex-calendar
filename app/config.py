from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    app_name: str
    secret_key: str
    app_username: str
    app_password: str
    password_login_enabled: bool
    database_url: str
    yandex_client_id: str
    yandex_client_secret: str
    oauth_url: str
    calendar_api_base: str
    default_time_zone: str
    max_calendar_days: int
    request_timeout: float
    sso_enabled: bool
    sso_provider_name: str
    sso_authorization_url: str
    sso_token_url: str
    sso_userinfo_url: str
    sso_client_id: str
    sso_client_secret: str
    sso_client_auth_method: str
    sso_redirect_uri: str
    sso_scopes: str

    @classmethod
    def from_environment(cls, env_file: Path | None = None) -> "Settings":
        load_dotenv(env_file or BASE_DIR / ".env", override=False)

        def env(name: str, default: str = "") -> str:
            return os.getenv(name) or default

        database_url = env("DATABASE_URL") or env("database_url")
        if not database_url:
            postgres_host = env("POSTGRES_HOST")
            postgres_db = env("POSTGRES_DB")
            postgres_user = env("POSTGRES_USER")
            postgres_password = env("POSTGRES_PASSWORD")
            postgres_port = env("POSTGRES_PORT", "5432")
            if postgres_host and postgres_db and postgres_user and postgres_password:
                database_url = (
                    f"postgresql://{postgres_user}:{postgres_password}"
                    f"@{postgres_host}:{postgres_port}/{postgres_db}"
                )
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url.removeprefix("postgres://")

        sso_enabled = env("SSO_ENABLED", "false").strip().lower() in {"true", "1", "yes"}
        password_login_raw = env("PASSWORD_LOGIN_ENABLED")
        password_login_enabled = (
            password_login_raw.strip().lower() in {"true", "1", "yes"}
            if password_login_raw
            else not sso_enabled
        )

        return cls(
            app_name=env("APP_NAME", "Яндекс Календарь"),
            secret_key=env("SECRET_KEY", "change-this-secret-key"),
            app_username=env("APP_USERNAME", "admin"),
            app_password=env("APP_PASSWORD", "change-me"),
            password_login_enabled=password_login_enabled,
            database_url=database_url,
            yandex_client_id=env("YANDEX_CLIENT_ID"),
            yandex_client_secret=env("YANDEX_CLIENT_SECRET"),
            oauth_url=env("YANDEX_OAUTH_URL", "https://oauth.yandex.ru/token").rstrip("/"),
            calendar_api_base=env(
                "YANDEX_CALENDAR_API_BASE", "https://cloud-api.yandex.net/v1/calendar"
            ).rstrip("/"),
            default_time_zone=env("DEFAULT_TIME_ZONE", "Asia/Yekaterinburg"),
            max_calendar_days=int(env("MAX_CALENDAR_DAYS", "31")),
            request_timeout=float(env("REQUEST_TIMEOUT", "30")),
            sso_enabled=sso_enabled,
            sso_provider_name=env("SSO_PROVIDER_NAME", "SSO").strip(),
            sso_authorization_url=env("SSO_AUTHORIZATION_URL").strip(),
            sso_token_url=env("SSO_TOKEN_URL").strip(),
            sso_userinfo_url=env("SSO_USERINFO_URL").strip(),
            sso_client_id=env("SSO_CLIENT_ID").strip(),
            sso_client_secret=env("SSO_CLIENT_SECRET").strip(),
            sso_client_auth_method=env("SSO_CLIENT_AUTH_METHOD", "post").strip().lower(),
            sso_redirect_uri=env("SSO_REDIRECT_URI").strip(),
            sso_scopes=env("SSO_SCOPES", "openid email profile").strip(),
        )
