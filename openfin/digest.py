from __future__ import annotations

from datetime import timedelta
from typing import Literal

import typer

from openfin.delivery import DeliveryError, deliver_digest
from openfin.dates import task_due_date, today_date
from openfin.storage import OpenFinStore
from openfin.task import (
    active_tasks,
    format_task_line,
    sort_tasks,
    visible_due_today,
    visible_overdue,
)
from openfin.ui import console


DigestKind = Literal["morning", "evening"]
DeliveryTarget = Literal["none", "desktop", "telegram", "both"]


def digest(
    kind: str = typer.Argument(
        "morning",
        help="Digest kind to render: morning or evening.",
    ),
    send: str = typer.Option(
        "none",
        "--send",
        help="Delivery target after rendering: none, desktop, telegram, or both.",
    ),
) -> None:
    """Render a morning or evening brief."""
    normalized = normalize_digest_kind(kind)
    target = normalize_delivery_target(send)

    store = OpenFinStore.from_env()
    rendered = render_digest(store, normalized)
    console.print(rendered, markup=False)

    if target == "none":
        return

    try:
        delivered = deliver_digest(
            title=f"OpenFin {normalized} digest", message=rendered, target=target
        )
    except DeliveryError as exc:
        console.print(f"Delivery failed: {exc}")
        raise typer.Exit(1) from exc

    console.print(f"Sent digest via {', '.join(delivered)}.")


def normalize_digest_kind(kind: str) -> DigestKind:
    normalized = kind.lower()
    if normalized not in {"morning", "evening"}:
        raise typer.BadParameter("digest kind must be morning or evening")
    return normalized


def normalize_delivery_target(target: str) -> DeliveryTarget:
    normalized = target.lower()
    if normalized not in {"none", "desktop", "telegram", "both"}:
        raise typer.BadParameter(
            "delivery target must be none, desktop, telegram, or both"
        )
    return normalized


def render_digest(store: OpenFinStore, kind: DigestKind) -> str:
    tasks = store.load_tasks()
    today = today_date()
    active = active_tasks(tasks)
    overdue_tasks = [task for task in active if visible_overdue(task, today)]

    if kind == "morning":
        return "\n".join(
            [
                "MORNING DIGEST",
                "",
                render_digest_section("OVERDUE", sort_tasks(overdue_tasks)),
                "",
                render_digest_section(
                    "TODAY'S TOP 3",
                    sort_tasks(
                        [task for task in active if visible_due_today(task, today)]
                    )[:3],
                ),
                "",
                render_digest_section(
                    "IN FLIGHT",
                    [task for task in active if task.get("status") == "doing"],
                ),
                "",
                render_digest_section(
                    "WAITING ON",
                    [task for task in active if task.get("status") == "blocked"],
                ),
            ]
        ).strip()

    today_log = [
        entry.line
        for entry in store.log_entries(tags=["done"], on_date=today, limit=100)
    ]
    tomorrow_tasks = sort_tasks(
        [
            task
            for task in active
            if (due := task_due_date(task)) is not None
            and due == today + timedelta(days=1)
        ]
    )[:3]
    return "\n".join(
        [
            "EVENING DIGEST",
            "",
            render_log_section("CLOSED TODAY", today_log[:10]),
            "",
            render_digest_section("TOMORROW'S TOP 3", tomorrow_tasks),
            "",
            render_digest_section("SLIPPING", sort_tasks(overdue_tasks)),
        ]
    ).strip()


def render_digest_section(title: str, tasks: list[dict]) -> str:
    if not tasks:
        return f"{title}\n- none"
    return "\n".join([title, *[format_task_line(task) for task in tasks]])


def render_log_section(title: str, entries: list[str]) -> str:
    if not entries:
        return f"{title}\n- none"
    return "\n".join([title, *entries])
