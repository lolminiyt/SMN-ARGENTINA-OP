"""Helpers for parsing SMN alert payloads."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .const import ALERT_EVENT_MAP, ALERT_LEVEL_MAP


def iter_warning_events(
    alerts: dict[str, Any] | None,
) -> Iterator[tuple[str | None, dict[str, Any]]]:
    """Yield (date, event) pairs for every warning day in the payload."""
    if not isinstance(alerts, dict):
        return

    for warning in alerts.get("warnings") or []:
        if not isinstance(warning, dict):
            continue
        day = warning.get("date")
        for event in warning.get("events") or []:
            if isinstance(event, dict):
                yield day, event


def _as_level(value: Any) -> int | None:
    """Coerce an SMN level to an int, accepting numeric strings."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _as_event_id(value: Any) -> Any:
    """Normalize a string event ID to an int when possible."""
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value


def event_level(event: dict[str, Any]) -> int:
    """Return the maximum level of an alert event.

    SMN normally sends ``max_level``, but older/newer payloads may only send a
    per-period ``levels`` mapping or list.
    """
    level = _as_level(event.get("max_level"))
    if level is None:
        level = _as_level(event.get("level"))
    if level is not None:
        return level

    levels = event.get("levels")
    values: list[int] = []
    if isinstance(levels, dict):
        values = [
            parsed
            for value in levels.values()
            if (parsed := _as_level(value)) is not None
        ]
    elif isinstance(levels, list):
        values = [
            parsed
            for item in levels
            if isinstance(item, dict)
            and (parsed := _as_level(item.get("level"))) is not None
        ]

    return max(values) if values else 1


def alert_level_info(level: int) -> dict[str, Any]:
    """Return display metadata for an SMN alert level.

    Unknown or future levels are clamped so a red/extreme alert is never
    downgraded to the informational fallback.
    """
    if level <= 1:
        return ALERT_LEVEL_MAP[1]
    if level >= 5:
        return ALERT_LEVEL_MAP[5]
    return ALERT_LEVEL_MAP.get(level, ALERT_LEVEL_MAP[1])


def _report_details(
    alerts: dict[str, Any], event_id: int | None, level: int
) -> tuple[str | None, str | None]:
    """Find the description/instruction for an event and level."""
    reports = alerts.get("reports") or []
    if isinstance(reports, dict):
        items: list[tuple[Any, Any]] = list(reports.items())
    elif isinstance(reports, list):
        items = [(None, report) for report in reports]
    else:
        return None, None

    for report_id, report in items:
        if not isinstance(report, dict):
            continue

        report_event_id = _as_event_id(
            report.get("event_id", report.get("id", report_id))
        )
        if report_event_id != event_id:
            continue

        if _as_level(report.get("level")) == level:
            return report.get("description"), report.get("instruction")

        levels = report.get("levels") or []
        if isinstance(levels, dict):
            # Either a mapping of period -> level, or a single level object.
            if "level" in levels:
                levels = [levels]
            else:
                levels = list(levels.values())

        for level_data in levels:
            if (
                isinstance(level_data, dict)
                and _as_level(level_data.get("level")) == level
            ):
                return level_data.get("description"), level_data.get("instruction")
            if _as_level(level_data) == level:
                return report.get("description"), report.get("instruction")

    return None, None


def active_alerts(alerts: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return all active (level > 1) alerts with resolved metadata."""
    if not isinstance(alerts, dict):
        return []

    result: list[dict[str, Any]] = []
    for day, event in iter_warning_events(alerts):
        level = event_level(event)
        if level <= 1:
            continue

        event_id: Any = _as_event_id(event.get("id"))
        level_info = alert_level_info(level)
        description, instruction = _report_details(alerts, event_id, level)
        description = description or event.get("description")
        instruction = instruction or event.get("instruction")

        result.append(
            {
                "date": day,
                "event_id": event_id,
                "event_name": ALERT_EVENT_MAP.get(event_id, f"unknown_{event_id}"),
                "level": level,
                "level_name": level_info["name"],
                "color": level_info["color"],
                "severity": level_info["severity"],
                "description": description,
                "instruction": instruction,
            }
        )

    return result


def parse_alerts(alerts: dict[str, Any] | None) -> dict[str, Any]:
    """Parse raw alerts data into a structured format for automations."""
    if not isinstance(alerts, dict):
        return {
            "active_alerts": [],
            "max_severity": "info",
            "max_level": 1,
            "area_id": None,
            "updated": None,
        }

    active = active_alerts(alerts)
    max_level = max((alert["level"] for alert in active), default=1)
    max_severity_info = alert_level_info(max_level)

    return {
        "active_alerts": active,
        "max_severity": max_severity_info["severity"],
        "max_level": max_level,
        "area_id": alerts.get("area_id"),
        "updated": alerts.get("updated"),
    }
