from __future__ import annotations

from datetime import date

import typer

from openfin.dates import parse_date_input
from openfin.storage import OpenFinStore
from openfin.ui import console


def search(
    query: str,
    tag: str | None = typer.Option(None, "--tag"),
    since: str | None = typer.Option(None, "--since"),
) -> None:
    """Search across charter, now, tasks, inbox, and log files."""
    store = OpenFinStore.from_env()
    since_date = date.fromisoformat(parse_date_input(since)) if since else None
    hits = store.search(query, tag=tag, since=since_date)
    if not hits:
        console.print("No matches.")
        return
    for hit in hits:
        console.print(f"{hit.source}:{hit.line_number}: {hit.line}", markup=False)
