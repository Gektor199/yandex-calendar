from __future__ import annotations

import json
import asyncio
from datetime import date, datetime, time, timezone, timedelta

import httpx

from app.config import Settings


class CalendarClientError(RuntimeError):
    pass


def date_chunks(from_date: date, to_date: date) -> list[tuple[date, date]]:
    chunks = []
    cursor = from_date
    while cursor <= to_date:
        chunk_end = min(cursor + timedelta(days=6), to_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def yandex_datetime_boundary(value: date, *, end_of_day: bool) -> str:
    boundary_time = time(23, 59, 59) if end_of_day else time(0, 0, 0)
    boundary = datetime.combine(value, boundary_time, tzinfo=timezone.utc)
    return boundary.strftime("%Y-%m-%dT%H:%M:%SZ")


class CalendarClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http_client = http_client

    async def events_for_user(
        self, email: str, from_date: date, to_date: date, time_zone: str
    ) -> list[dict]:
        token = await self._token_for_user(email)
        events: list[dict] = []
        seen: set[tuple[str, str, str]] = set()
        for chunk_from, chunk_to in date_chunks(from_date, to_date):
            iteration_key = ""
            while True:
                params = {
                    "from": yandex_datetime_boundary(chunk_from, end_of_day=False),
                    "to": yandex_datetime_boundary(chunk_to, end_of_day=True),
                    "time_zone": time_zone,
                    "limit": "100",
                }
                if iteration_key:
                    params["iteration_key"] = iteration_key
                try:
                    response = await self.http_client.get(
                        f"{self.settings.calendar_api_base}/events",
                        params=params,
                        headers={"Authorization": f"OAuth {token}", "Accept": "application/json"},
                    )
                except httpx.HTTPError as exc:
                    raise CalendarClientError(f"Calendar API недоступен: {exc}") from exc
                if response.status_code >= 400:
                    raise CalendarClientError(self._error_message("Calendar API", response))
                payload = self._json(response, "Calendar API")
                for event in payload.get("items", []):
                    if not isinstance(event, dict):
                        continue
                    key = (
                        str(event.get("event_id", "")),
                        str(event.get("recurrence_id", "")),
                        str(event.get("start", ""))
                        or json.dumps(event, ensure_ascii=False, sort_keys=True),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    events.append(event)
                next_iteration_key = str(payload.get("iteration_key", "")).strip()
                if not next_iteration_key or next_iteration_key == iteration_key:
                    break
                iteration_key = next_iteration_key
        return await self._events_with_participants(events, token)

    async def _events_with_participants(self, events: list[dict], token: str) -> list[dict]:
        semaphore = asyncio.Semaphore(4)

        async def enrich(event: dict) -> dict:
            event_id = str(event.get("event_id", "")).strip()
            if not event_id:
                return event
            enriched = dict(event)
            try:
                async with semaphore:
                    enriched["participants"] = await self._participants_for_event(event_id, token)
            except CalendarClientError:
                enriched["participants"] = []
            return enriched

        return await asyncio.gather(*(enrich(event) for event in events))

    async def _participants_for_event(self, event_id: str, token: str) -> list[dict]:
        try:
            response = await self.http_client.get(
                f"{self.settings.calendar_api_base}/events/{event_id}/participants",
                headers={"Authorization": f"OAuth {token}", "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise CalendarClientError(f"Calendar participants API недоступен: {exc}") from exc
        if response.status_code >= 400:
            raise CalendarClientError(self._error_message("Calendar participants API", response))
        payload = self._json(response, "Calendar participants API")
        return [item for item in payload.get("items", []) if isinstance(item, dict)]

    async def _token_for_user(self, email: str) -> str:
        if not self.settings.yandex_client_id or not self.settings.yandex_client_secret:
            raise CalendarClientError("В env не заполнены YANDEX_CLIENT_ID и YANDEX_CLIENT_SECRET.")
        try:
            response = await self.http_client.post(
                self.settings.oauth_url,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                    "client_id": self.settings.yandex_client_id,
                    "client_secret": self.settings.yandex_client_secret,
                    "subject_token": email,
                    "subject_token_type": "urn:yandex:params:oauth:token-type:email",
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise CalendarClientError(f"OAuth недоступен: {exc}") from exc
        if response.status_code >= 400:
            raise CalendarClientError(self._error_message("OAuth", response))
        payload = self._json(response, "OAuth")
        token = str(payload.get("access_token", "")).strip()
        if not token:
            raise CalendarClientError("OAuth не вернул access_token.")
        return token

    @staticmethod
    def _json(response: httpx.Response, service: str) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise CalendarClientError(f"{service} вернул невалидный JSON.") from exc
        if not isinstance(payload, dict):
            raise CalendarClientError(f"{service} вернул неожиданный формат ответа.")
        return payload

    @staticmethod
    def _error_message(service: str, response: httpx.Response) -> str:
        try:
            payload = response.json()
            description = (
                payload.get("message") or payload.get("error_description") or payload.get("error")
                if isinstance(payload, dict)
                else str(payload)[:200]
            )
        except ValueError:
            description = response.text[:200]
        suffix = f": {description}" if description else ""
        return f"{service} вернул HTTP {response.status_code}{suffix}"
