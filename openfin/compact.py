from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from openfin.dates import task_due_date, today_date
from openfin.storage import OpenFinStore
from openfin.task import active_tasks, format_task_line, visible_overdue
from openfin.ui import console


def compact() -> None:
    """Archive old closed tasks and print stale/redundancy suggestions."""
    store = OpenFinStore.from_env()
    tasks = store.load_tasks()
    today = today_date()
    archive_cutoff = today - timedelta(days=14)
    stale_cutoff = today - timedelta(days=7)
    kept: list[dict[str, Any]] = []
    archived: list[dict[str, Any]] = []

    for task in tasks:
        updated = task_due_date(task, "updated")
        if (
            task.get("status") in {"done", "dropped"}
            and updated
            and updated < archive_cutoff
        ):
            archived.append(task)
            marker = "done" if task.get("status") == "done" else "dropped"
            task_id = str(task.get("id"))
            if not store.has_log_marker(marker, task_id):
                store.append_log_entry(f"#{marker} {task_id} {task.get('title')}")
        else:
            kept.append(task)

    if archived:
        store.save_tasks(kept)
        console.print(f"Archived {len(archived)} closed task(s) into the log.")
    else:
        console.print("No closed tasks old enough to archive.")

    stale = [
        task
        for task in active_tasks(kept)
        if (updated := task_due_date(task, "updated")) and updated < stale_cutoff
    ]
    if stale:
        console.print("STALE - still true?")
        for task in stale:
            console.print(format_task_line(task), markup=False)

    redundant = find_tag_collisions(kept, today=today)
    if redundant:
        console.print("POSSIBLE REDUNDANCY")
        for tag, tasks_for_tag in redundant.items():
            ids = ", ".join(str(task.get("id")) for task in tasks_for_tag)
            console.print(f"#{tag}: {ids}")


def find_tag_collisions(
    tasks: list[dict[str, Any]],
    *,
    today: date,
) -> dict[str, list[dict[str, Any]]]:
    by_tag: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        if task.get("status") != "open":
            continue
        for tag in task.get("tags") or []:
            by_tag.setdefault(str(tag), []).append(task)
    return {
        tag: tagged
        for tag, tagged in by_tag.items()
        if len(tagged) >= 2
        and any(is_redundancy_candidate(task, today) for task in tagged)
    }


def is_redundancy_candidate(task: dict[str, Any], today: date) -> bool:
    if visible_overdue(task, today):
        return True
    created = task_due_date(task, "created")
    return created is not None and created < today - timedelta(days=7)
