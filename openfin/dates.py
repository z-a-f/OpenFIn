from __future__ import annotations

from datetime import date, datetime
from typing import Any

import typer


def today_date() -> date:
    return date.today()


def parse_date_input(value: str | None) -> str | None:
    if not value:
        return None
    import dateparser

    parsed = dateparser.parse(
        value,
        settings={
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": datetime.now(),
        },
    )
    if parsed is None:
        raise typer.BadParameter(f"could not parse date: {value}")
    return parsed.date().isoformat()


def task_due_date(task: dict[str, Any], field: str = "due") -> date | None:
    value = task.get(field)
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def invalid_task_dates(task: dict[str, Any]) -> list[str]:
    invalid: list[str] = []
    for field in ["due", "recheck", "created", "updated"]:
        value = task.get(field)
        if not value:
            continue
        try:
            date.fromisoformat(str(value))
        except ValueError:
            invalid.append(f"{task.get('id')} {field}={value}")
    return invalid
