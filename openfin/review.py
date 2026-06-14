from __future__ import annotations

from datetime import timedelta

import typer

from openfin.dates import parse_date_input, today_date
from openfin.storage import OpenFinStore
from openfin.task import (
    active_tasks,
    append_task_log,
    format_task_line,
    needs_review,
    sort_tasks,
    update_task_timestamp,
)
from openfin.ui import console


def review() -> None:
    """Interactive decision loop for overdue and recheck tasks."""
    store = OpenFinStore.from_env()
    tasks = store.load_tasks()
    today = today_date()
    review_items = [task for task in active_tasks(tasks) if needs_review(task, today)]
    if not review_items:
        console.print("No overdue or recheck items.")
        return

    for task in sort_tasks(review_items):
        console.print(format_task_line(task), markup=False)
        choice = (
            typer.prompt(
                "Decision [commit/snooze/block/drop/done/skip]",
                default="skip",
            )
            .strip()
            .lower()
        )
        if choice == "commit":
            days_raw = typer.prompt("Recheck in days", default="1")
            try:
                days = int(days_raw)
            except ValueError as exc:
                raise typer.BadParameter("recheck days must be an integer") from exc
            recheck_date = today + timedelta(days=days)
            task["recheck"] = recheck_date.isoformat()
            update_task_timestamp(task)
            store.append_log_entry(
                f"#commit {task['id']} recheck {recheck_date.isoformat()}"
            )
        elif choice == "snooze":
            new_due = typer.prompt("New due date")
            task["due"] = parse_date_input(new_due)
            update_task_timestamp(task)
        elif choice == "block":
            why = typer.prompt("Why blocked")
            task["status"] = "blocked"
            prior_notes = task.get("notes") or ""
            task["notes"] = f"{prior_notes}\nBlocked {today.isoformat()}: {why}".strip()
            update_task_timestamp(task)
        elif choice == "drop":
            task["status"] = "dropped"
            task["recheck"] = None
            update_task_timestamp(task)
            append_task_log(store, "dropped", task)
        elif choice == "done":
            task["status"] = "done"
            task["recheck"] = None
            update_task_timestamp(task)
            append_task_log(store, "done", task)
        elif choice == "skip":
            continue
        else:
            console.print(f"Skipped unknown decision: {choice}")
    store.save_tasks(tasks)
    console.print("Review complete.")
