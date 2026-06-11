from __future__ import annotations

from datetime import date, datetime, time, timedelta
from html import unescape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


STATUS_LABELS = {
    "accepted": "придет",
    "accept": "придет",
    "yes": "придет",
    "true": "придет",
    "declined": "не придет",
    "decline": "не придет",
    "no": "не придет",
    "false": "не придет",
    "tentative": "под вопросом",
    "maybe": "под вопросом",
    "needs_action": "",
    "needs-action": "",
    "none": "",
}


def zone(time_zone: str) -> ZoneInfo:
    try:
        return ZoneInfo(time_zone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def parse_datetime(value: str, time_zone: str) -> datetime:
    clean_value = value.strip()
    if clean_value.endswith("Z"):
        clean_value = clean_value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(clean_value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone(time_zone))
    return parsed


def event_datetime(event: dict, field: str, time_zone: str) -> datetime:
    value = event.get(field) if isinstance(event.get(field), dict) else {}
    if value.get("date_time"):
        return parse_datetime(str(value["date_time"]), str(value.get("time_zone") or time_zone))
    if value.get("date"):
        return datetime.combine(date.fromisoformat(str(value["date"])), time.min, tzinfo=zone(time_zone))
    return datetime.now(zone(time_zone))


def event_participants(event: dict) -> list[dict]:
    raw_items = (
        event.get("participants")
        or event.get("attendees")
        or event.get("members")
        or event.get("resources")
        or []
    )
    if not isinstance(raw_items, list):
        return []
    result = []
    seen = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        name = (
            item.get("name")
            or item.get("display_name")
            or item.get("displayName")
            or item.get("email")
            or item.get("login")
            or ""
        )
        email = item.get("email") or item.get("login") or ""
        status = (
            item.get("status")
            or item.get("decision")
            or item.get("response_status")
            or item.get("responseStatus")
            or item.get("participation_status")
            or ""
        )
        clean_name = str(name or "").strip()
        clean_email = str(email or "").strip()
        clean_status = STATUS_LABELS.get(str(status or "").strip().lower(), str(status or "").strip())
        key = (clean_name.lower(), clean_email.lower())
        if not clean_name or key in seen:
            continue
        seen.add(key)
        result.append({"name": clean_name, "email": clean_email, "status": clean_status})
    return result


def normalize_events(events: list[dict], time_zone: str) -> list[dict]:
    target_zone = zone(time_zone)
    normalized = []
    for index, event in enumerate(events):
        start = event_datetime(event, "start", time_zone).astimezone(target_zone)
        end = event_datetime(event, "end", time_zone).astimezone(target_zone)
        if end <= start:
            end = start + timedelta(minutes=30)
        normalized.append(
            {
                "id": str(event.get("event_id") or f"event-{index}"),
                "title": str(event.get("summary") or "Без названия"),
                "location": str(event.get("location") or ""),
                "description": unescape(str(event.get("description") or "")),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "day": start.date().isoformat(),
                "start_minutes": start.hour * 60 + start.minute,
                "end_minutes": end.hour * 60 + end.minute,
                "participants": event_participants(event),
            }
        )
    return sorted(normalized, key=lambda item: (item["start"], item["title"]))
