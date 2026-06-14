from __future__ import annotations

import typer

from openfin.storage import OpenFinStore, read_text
from openfin.tags import task_matches_profile
from openfin.task import active_tasks, format_task_line, sort_tasks
from openfin.ui import console


def context(
    profile: str = typer.Argument("default"),
    topic: str | None = typer.Option(None, "--for"),
    copy: bool = typer.Option(False, "--copy"),
    budget: int | None = typer.Option(None, "--budget"),
) -> None:
    """Assemble an AI-ready context pack."""
    store = OpenFinStore.from_env()
    pack = assemble_context_pack(store, profile_name=profile, topic=topic)
    token_estimate = max(1, len(pack) // 4)
    if copy:
        import pyperclip

        pyperclip.copy(pack)
        console.print("Copied context pack to clipboard.")
    else:
        console.print(pack, markup=False)
    console.print(f"\nEstimated tokens: {token_estimate}")
    if budget is not None and token_estimate > budget:
        console.print(f"Budget warning: estimated tokens exceed {budget}.")


def assemble_context_pack(
    store: OpenFinStore,
    *,
    profile_name: str,
    topic: str | None,
) -> str:
    profiles = store.load_profiles()
    if profile_name not in profiles:
        raise typer.BadParameter(f"unknown profile: {profile_name}")

    profile = profiles[profile_name]
    charter = select_charter_sections(
        read_text(store.charter_path),
        profile.get("charter_sections", "all"),
    )
    now = read_text(store.now_path).strip()
    task_tags = profile.get("task_tags", "all")
    tasks = [
        task
        for task in sort_tasks(active_tasks(store.load_tasks()))
        if task_matches_profile(task, task_tags)
    ]
    log_tags = profile.get("log_tags", "all")
    max_log_lines = int(profile.get("max_log_lines", 40))
    log_entries = store.recent_log_entries(tags=log_tags, limit=max_log_lines)

    parts = [
        "# OpenFin Context Pack",
        f"Profile: {profile_name}",
        "",
        "## Charter",
        charter,
        "",
        "## Now",
        now,
        "",
        "## Open Tasks",
        "\n".join(format_task_line(task) for task in tasks) or "- none",
        "",
        "## Recent Log",
        "\n".join(log_entries) or "- none",
    ]
    if topic:
        hits = store.search(topic)
        parts.extend(
            [
                "",
                f"## Topic Hits: {topic}",
                "\n".join(
                    f"- {hit.source}:{hit.line_number}: {hit.line}" for hit in hits
                )
                or "- none",
            ]
        )
    return "\n".join(parts).strip()


def select_charter_sections(text: str, sections: list[str] | str) -> str:
    if sections == "all":
        return text.strip()

    wanted = {section.strip() for section in sections}
    output: list[str] = []
    include = False
    for line in text.splitlines():
        if line.startswith("# ") and not output:
            output.append(line)
            continue
        if line.startswith("## "):
            name = line.removeprefix("## ").strip()
            include = name in wanted
        if include:
            output.append(line)
    return "\n".join(output).strip()
