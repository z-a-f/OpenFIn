from __future__ import annotations

import re

import typer

from openfin.dates import today_date
from openfin.storage import OpenFinStore, read_text
from openfin.tags import parse_tags
from openfin.task import build_task
from openfin.ui import console


def capture(text: str) -> None:
    """Append a raw line to inbox.md."""
    store = OpenFinStore.from_env()
    store.append_inbox(text)
    console.print("Captured.")


def idea(
    text: str,
    tags: str | None = typer.Option(None, "--tag", "-t"),
) -> None:
    """Append an idea to the current month's log."""
    store = OpenFinStore.from_env()
    markers = " ".join(f"#{tag}" for tag in parse_tags(tags))
    body = f"#idea {markers} {text}".replace("  ", " ").strip()
    store.append_log_entry(body)
    console.print("Logged idea.")


def triage() -> None:
    """Interactively triage inbox lines into tasks, ideas, decisions, notes, or drops."""
    store = OpenFinStore.from_env()
    store.ensure_layout()
    lines = [line for line in read_text(store.inbox_path).splitlines() if line.strip()]
    if not lines:
        console.print("Inbox is empty.")
        return

    remaining: list[str] = []
    tasks = store.load_tasks()
    for line in lines:
        text = re.sub(r"^-\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+", "", line).strip()
        console.print(line, markup=False)
        choice = typer.prompt(
            "Triage [task/idea/decision/note/drop/skip]", default="skip"
        ).lower()
        if choice == "task":
            task = build_task(store, tasks, text)
            task["created"] = today_date().isoformat()
            task["updated"] = task["created"]
            tasks.append(task)
            console.print(f"Added {task['id']}.")
        elif choice == "idea":
            store.append_log_entry(f"#idea {text}")
        elif choice == "decision":
            store.append_log_entry(f"#decision {text}")
        elif choice == "note":
            store.append_log_entry(f"#note {text}")
        elif choice == "drop":
            continue
        else:
            remaining.append(line)
    store.save_tasks(tasks)
    store.write_inbox_lines(remaining)
    console.print("Triage complete.")
