from __future__ import annotations

from datetime import timedelta

import typer

from openfin.dates import task_due_date, today_date
from openfin.storage import OpenFinStore
from openfin.task import active_tasks, sort_tasks, visible_due_today, visible_overdue
from openfin.ui import console, render_tasks


def digest(kind: str = typer.Argument("morning")) -> None:
    """Render a morning or evening brief."""
    normalized = kind.lower()
    if normalized not in {"morning", "evening"}:
        raise typer.BadParameter("digest kind must be morning or evening")

    store = OpenFinStore.from_env()
    tasks = store.load_tasks()
    today = today_date()
    active = active_tasks(tasks)
    overdue_tasks = [task for task in active if visible_overdue(task, today)]

    if normalized == "morning":
        console.print("MORNING DIGEST")
        render_tasks(sort_tasks(overdue_tasks), title="OVERDUE")
        render_tasks(
            sort_tasks([task for task in active if visible_due_today(task, today)])[:3],
            title="TODAY'S TOP 3",
        )
        render_tasks(
            [task for task in active if task.get("status") == "doing"],
            title="IN FLIGHT",
        )
        render_tasks(
            [task for task in active if task.get("status") == "blocked"],
            title="WAITING ON",
        )
        return

    console.print("EVENING DIGEST")
    today_log = [
        entry.line
        for entry in store.log_entries(tags=["done"], on_date=today, limit=100)
    ]
    for entry in today_log[:10]:
        console.print(entry, markup=False)
    render_tasks(
        sort_tasks(
            [
                task
                for task in active
                if (due := task_due_date(task)) is not None
                and due == today + timedelta(days=1)
            ]
        )[:3],
        title="TOMORROW'S TOP 3",
    )
    render_tasks(sort_tasks(overdue_tasks), title="SLIPPING")
