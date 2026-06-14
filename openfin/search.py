from __future__ import annotations

from datetime import date

import typer

from openfin.dates import parse_date_input
from openfin.index import search_index
from openfin.storage import OpenFinStore
from openfin.ui import console


def search(
    query: str = typer.Argument(
        ...,
        help="Text to search for across OpenFin memory files.",
    ),
    tag: str | None = typer.Option(
        None,
        "--tag",
        help="Only return lines containing this tag. Leading # is optional.",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Only return dated hits on or after this date, e.g. 'last week'.",
    ),
    use_index: bool = typer.Option(
        False,
        "--index",
        help="Search the derived SQLite FTS index instead of scanning files directly.",
    ),
) -> None:
    """Search across charter, now, tasks, inbox, and log files."""
    store = OpenFinStore.from_env()
    since_date = parse_since_date(since)
    hits = (
        search_index(store, query, tag=tag, since=since_date)
        if use_index
        else store.search(query, tag=tag, since=since_date)
    )
    print_hits(hits)


def parse_since_date(since: str | None) -> date | None:
    return date.fromisoformat(parse_date_input(since)) if since else None


def print_hits(hits) -> None:
    if not hits:
        console.print("No matches.")
        return
    for hit in hits:
        console.print(f"{hit.source}:{hit.line_number}: {hit.line}", markup=False)
