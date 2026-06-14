from __future__ import annotations

from typing import Any

import typer


class PlainConsole:
    def print(self, *objects: Any, **_: Any) -> None:
        typer.echo(" ".join(str(item) for item in objects))


console = PlainConsole()


def render_tasks(tasks: list[dict[str, Any]], *, title: str) -> None:
    if not tasks:
        console.print(f"{title}: none")
        return

    from rich.console import Console
    from rich.table import Table

    rich_console = Console(color_system=None, highlight=False)
    table = Table(title=title)
    table.add_column("ID")
    table.add_column("Priority")
    table.add_column("Status")
    table.add_column("Due")
    table.add_column("Tags")
    table.add_column("Title")
    for task in tasks:
        tags = ", ".join(task.get("tags") or [])
        table.add_row(
            str(task.get("id", "")),
            str(task.get("priority", "")),
            str(task.get("status", "")),
            str(task.get("due") or ""),
            tags,
            str(task.get("title", "")),
        )
    rich_console.print(table)
