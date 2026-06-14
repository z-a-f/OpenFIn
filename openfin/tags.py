from __future__ import annotations

from typing import Any


def parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip().lstrip("#") for item in value.split(",") if item.strip()]


def tag_matches(task: dict[str, Any], tag: str | None) -> bool:
    if not tag:
        return True
    wanted = tag.lstrip("#")
    return wanted in [str(item).lstrip("#") for item in task.get("tags") or []]


def task_matches_profile(task: dict[str, Any], tags: list[str] | str) -> bool:
    if tags == "all":
        return True
    task_tags = {str(item).lstrip("#") for item in task.get("tags") or []}
    return bool(task_tags.intersection({tag.lstrip("#") for tag in tags}))
