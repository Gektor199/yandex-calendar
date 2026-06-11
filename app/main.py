from __future__ import annotations

import asyncio
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, timedelta

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from app.calendar_client import CalendarClient, CalendarClientError
from app.config import BASE_DIR, Settings
from app.database import DuplicateEmailError, PostgresDatabase
from app.event_normalizer import normalize_events
from app.sso import SSOClient, SSOError


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9._@-]+$")
CALENDAR_CACHE_TTL_SECONDS = 30
CALENDAR_STALE_TTL_SECONDS = 6 * 60 * 60
CALENDAR_ERROR_BACKOFF_SECONDS = 60


class AccessUserCreateRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    role: str = Field(pattern="^(admin|user)$")
    allow_all: bool = False
    allowed_calendars: list[str] = Field(default_factory=list)


class AccessUserUpdateRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    role: str = Field(pattern="^(admin|user)$")
    allow_all: bool = False
    allowed_calendars: list[str] = Field(default_factory=list)


def create_app(settings: Settings | None = None, database=None) -> FastAPI:
    current_settings = settings or Settings.from_environment()
    app_database = database or PostgresDatabase(current_settings.database_url)
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        app_database.initialize()
        yield

    app = FastAPI(title=current_settings.app_name, lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=current_settings.secret_key, same_site="lax")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    app.state.settings = current_settings
    app.state.database = app_database
    app.state.calendar_client_factory = lambda http_client: CalendarClient(current_settings, http_client)
    app.state.sso_client_factory = lambda http_client: SSOClient(current_settings, http_client)
    app.state.calendar_cache = {}
    app.state.calendar_error_backoff = {}
    app.state.calendar_cache_locks = {}

    def api_login_required(request: Request) -> None:
        if not request.session.get("authenticated"):
            raise HTTPException(status_code=401, detail="Требуется вход.")

    def admin_required(request: Request) -> None:
        api_login_required(request)
        if request.session.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Требуются права администратора.")

    def validate_email(email: str) -> str:
        clean_email = email.strip().lower()
        if not EMAIL_PATTERN.match(clean_email):
            raise HTTPException(status_code=400, detail="Укажите корректный email сотрудника.")
        return clean_email

    def validate_identity(identity: str) -> str:
        clean_identity = identity.strip().lower()
        if not clean_identity or not IDENTITY_PATTERN.match(clean_identity):
            raise HTTPException(status_code=400, detail="Укажите доменную учетку без пробелов.")
        return clean_identity

    def normalize_calendar_list(values: list[str]) -> list[str]:
        calendars = []
        for value in values:
            for item in re.split(r"[\s,;]+", value):
                clean_item = item.strip().lower()
                if not clean_item:
                    continue
                if not EMAIL_PATTERN.match(clean_item):
                    raise HTTPException(status_code=400, detail=f"Некорректный email календаря: {clean_item}")
                calendars.append(clean_item)
        return list(dict.fromkeys(calendars))

    def sso_is_configured() -> bool:
        return all(
            (
                current_settings.sso_enabled,
                current_settings.sso_authorization_url,
                current_settings.sso_token_url,
                current_settings.sso_userinfo_url,
                current_settings.sso_client_id,
                current_settings.sso_client_secret,
            )
        )

    def sso_redirect_uri_for_request(request: Request) -> str:
        if current_settings.sso_redirect_uri:
            return current_settings.sso_redirect_uri
        return str(request.url_for("sso_callback"))

    def login_context(error: str = "") -> dict:
        return {
            "title": current_settings.app_name,
            "error": error,
            "sso_enabled": sso_is_configured(),
            "password_login_enabled": current_settings.password_login_enabled,
            "sso_provider_name": current_settings.sso_provider_name,
        }

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        if request.session.get("authenticated"):
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context=login_context(),
        )

    @app.post("/login", response_class=HTMLResponse)
    def login(request: Request, username: str = Form(...), password: str = Form(...)):
        if not current_settings.password_login_enabled:
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context=login_context("Вход по паролю отключен. Используйте SSO."),
                status_code=403,
            )
        valid_user = secrets.compare_digest(username.strip(), current_settings.app_username)
        valid_password = secrets.compare_digest(password, current_settings.app_password)
        if not (valid_user and valid_password):
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context=login_context("Неверный логин или пароль."),
                status_code=401,
            )
        request.session["authenticated"] = True
        request.session["username"] = current_settings.app_username
        request.session["role"] = "admin"
        request.session["auth_method"] = "password"
        return RedirectResponse("/", status_code=303)

    @app.get("/sso/login")
    def sso_login(request: Request):
        if not sso_is_configured():
            raise HTTPException(status_code=404, detail="SSO не настроен.")
        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        request.session["sso_state"] = state
        request.session["sso_code_verifier"] = code_verifier
        redirect_url = SSOClient(current_settings, None).authorization_url(
            state=state,
            redirect_uri=sso_redirect_uri_for_request(request),
            code_verifier=code_verifier,
        )
        return RedirectResponse(redirect_url, status_code=303)

    @app.get("/sso/callback", response_class=HTMLResponse)
    async def sso_callback(request: Request, code: str = "", state: str = "", error: str = ""):
        if not sso_is_configured():
            raise HTTPException(status_code=404, detail="SSO не настроен.")
        expected_state = request.session.pop("sso_state", "")
        code_verifier = request.session.pop("sso_code_verifier", "")
        if error:
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context=login_context(f"SSO вернул ошибку: {error}"),
                status_code=401,
            )
        if not code or not state or not secrets.compare_digest(state, expected_state):
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context=login_context("SSO-сессия устарела или некорректна."),
                status_code=401,
            )
        async with httpx.AsyncClient(timeout=current_settings.request_timeout) as http_client:
            try:
                profile = await request.app.state.sso_client_factory(http_client).profile_from_code(
                    code=code,
                    redirect_uri=sso_redirect_uri_for_request(request),
                    code_verifier=code_verifier,
                )
            except SSOError as exc:
                return templates.TemplateResponse(
                    request=request,
                    name="login.html",
                    context=login_context(str(exc)),
                    status_code=401,
                )
        access_user = request.app.state.database.get_access_user_by_email(profile.email)
        if not access_user:
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context=login_context("У этого SSO-пользователя нет доступа к приложению."),
                status_code=403,
            )
        request.app.state.database.update_access_user_name(profile.email, profile.name)
        request.session["authenticated"] = True
        request.session["username"] = profile.email
        request.session["role"] = access_user["role"]
        request.session["auth_method"] = "sso"
        return RedirectResponse("/", status_code=303)

    @app.get("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        if not request.session.get("authenticated"):
            return RedirectResponse("/login", status_code=303)
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "title": current_settings.app_name,
                "username": request.session.get("username", ""),
                "is_admin": request.session.get("role") == "admin",
                "week_start": week_start.isoformat(),
                "default_time_zone": current_settings.default_time_zone,
            },
        )

    @app.get("/admin", response_class=HTMLResponse)
    def admin_page(request: Request):
        if not request.session.get("authenticated"):
            return RedirectResponse("/login", status_code=303)
        if request.session.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Требуются права администратора.")
        return templates.TemplateResponse(
            request=request,
            name="admin.html",
            context={
                "title": current_settings.app_name,
                "username": request.session.get("username", ""),
            },
        )

    @app.get("/api/calendar/events", dependencies=[Depends(api_login_required)])
    async def calendar_events(
        request: Request,
        email: str = Query(min_length=1, max_length=320),
        from_date: date = Query(...),
        to_date: date = Query(...),
        time_zone: str = Query(default=current_settings.default_time_zone, min_length=1, max_length=100),
        refresh: bool = Query(default=False),
    ) -> dict:
        clean_email = validate_email(email)
        viewer_email = str(request.session.get("username", "")).strip().lower()
        if request.session.get("role") != "admin" and not request.app.state.database.user_can_access_calendar(
            viewer_email, clean_email
        ):
            raise HTTPException(status_code=403, detail="Нет доступа к календарю этого сотрудника.")
        if to_date < from_date:
            raise HTTPException(status_code=400, detail="Дата окончания раньше даты начала.")
        if (to_date - from_date).days + 1 > current_settings.max_calendar_days:
            raise HTTPException(
                status_code=400,
                detail=f"Запрос ограничен {current_settings.max_calendar_days} днями.",
            )
        clean_time_zone = time_zone.strip()
        cache_key = (clean_email, from_date.isoformat(), to_date.isoformat(), clean_time_zone)
        lock = request.app.state.calendar_cache_locks.setdefault(cache_key, asyncio.Lock())

        async with lock:
            now = time.monotonic()
            cached = request.app.state.calendar_cache.get(cache_key)
            if not refresh and cached and now - cached["stored_at"] <= CALENDAR_CACHE_TTL_SECONDS:
                return {**cached["payload"], "cached": True}

            backoff = request.app.state.calendar_error_backoff.get(cache_key)
            if backoff and now < backoff["retry_at"]:
                if cached and now - cached["stored_at"] <= CALENDAR_STALE_TTL_SECONDS:
                    return {**cached["payload"], "cached": True, "stale": True}
                raise HTTPException(status_code=502, detail=backoff["detail"])

            async with httpx.AsyncClient(timeout=current_settings.request_timeout) as http_client:
                try:
                    raw_events = await request.app.state.calendar_client_factory(http_client).events_for_user(
                        clean_email, from_date, to_date, clean_time_zone
                    )
                except CalendarClientError as exc:
                    detail = str(exc)
                    request.app.state.calendar_error_backoff[cache_key] = {
                        "detail": detail,
                        "retry_at": now + CALENDAR_ERROR_BACKOFF_SECONDS,
                    }
                    if cached and now - cached["stored_at"] <= CALENDAR_STALE_TTL_SECONDS:
                        return {**cached["payload"], "cached": True, "stale": True}
                    raise HTTPException(status_code=502, detail=detail) from exc

            payload = {
                "email": clean_email,
                "time_zone": clean_time_zone,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "items": normalize_events(raw_events, clean_time_zone),
            }
            request.app.state.calendar_cache[cache_key] = {"payload": payload, "stored_at": now}
            request.app.state.calendar_error_backoff.pop(cache_key, None)
            return payload

    @app.get("/api/me", dependencies=[Depends(api_login_required)])
    def current_user(request: Request) -> dict:
        return {
            "email": request.session.get("username", ""),
            "role": request.session.get("role", "user"),
            "is_admin": request.session.get("role") == "admin",
        }

    @app.get("/api/admin/access-users", dependencies=[Depends(admin_required)])
    def list_access_users(request: Request) -> dict:
        return {"items": request.app.state.database.list_access_users()}

    @app.post("/api/admin/access-users", dependencies=[Depends(admin_required)])
    def add_access_user(payload: AccessUserCreateRequest, request: Request) -> dict:
        email = validate_identity(payload.email)
        allowed_calendars = normalize_calendar_list(payload.allowed_calendars)
        try:
            request.app.state.database.add_access_user(
                email=email,
                role=payload.role,
                allow_all=payload.allow_all,
                allowed_calendars=allowed_calendars,
            )
        except DuplicateEmailError:
            raise HTTPException(status_code=409, detail="Пользователь уже есть в allow list.") from None
        return {"items": request.app.state.database.list_access_users()}

    @app.patch("/api/admin/access-users/{access_user_id}", dependencies=[Depends(admin_required)])
    def update_access_user(access_user_id: int, payload: AccessUserUpdateRequest, request: Request) -> dict:
        email = validate_identity(payload.email)
        allowed_calendars = normalize_calendar_list(payload.allowed_calendars)
        try:
            updated = request.app.state.database.update_access_user(
                access_user_id=access_user_id,
                email=email,
                role=payload.role,
                allow_all=payload.allow_all,
                allowed_calendars=allowed_calendars,
            )
        except DuplicateEmailError:
            raise HTTPException(status_code=409, detail="Пользователь с такой учеткой уже есть.") from None
        if not updated:
            raise HTTPException(status_code=404, detail="Пользователь allow list не найден.")
        return {"items": request.app.state.database.list_access_users()}

    @app.delete("/api/admin/access-users/{access_user_id}", dependencies=[Depends(admin_required)])
    def delete_access_user(access_user_id: int, request: Request) -> dict:
        deleted = request.app.state.database.delete_access_user(access_user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Пользователь allow list не найден.")
        return {"items": request.app.state.database.list_access_users()}

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return app


app = create_app()
