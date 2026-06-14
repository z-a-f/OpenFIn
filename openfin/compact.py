from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any

import typer

from openfin.dates import task_due_date, today_date
from openfin.storage import OpenFinStore
from openfin.task import active_tasks, format_task_line, visible_overdue
from openfin.ui import console


STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
}


@dataclass(frozen=True)
class DedupCandidate:
    first: dict[str, Any]
    second: dict[str, Any]
    score: float
    reason: str


def compact(
    deep_dedup: bool = typer.Option(
        False,
        "--deep-dedup",
        help="Print stricter title-similarity dedup candidates in addition to tag collisions.",
    ),
) -> None:
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

    if deep_dedup:
        candidates = find_deep_dedup_candidates(kept, today=today)
        if candidates:
            console.print("POSSIBLE DEEP DEDUP")
            for candidate in candidates:
                first_id = candidate.first.get("id")
                second_id = candidate.second.get("id")
                console.print(
                    f"{first_id} <-> {second_id} score {candidate.score:.2f} - {candidate.reason}"
                )


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


def find_deep_dedup_candidates(
    tasks: list[dict[str, Any]],
    *,
    today: date,
) -> list[DedupCandidate]:
    open_tasks = [task for task in tasks if task.get("status") == "open"]
    candidates: list[DedupCandidate] = []
    for index, first in enumerate(open_tasks):
        for second in open_tasks[index + 1 :]:
            candidate = score_dedup_pair(first, second, today=today)
            if candidate:
                candidates.append(candidate)
    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)


def score_dedup_pair(
    first: dict[str, Any],
    second: dict[str, Any],
    *,
    today: date,
) -> DedupCandidate | None:
    title_score = title_similarity(
        str(first.get("title", "")), str(second.get("title", ""))
    )
    token_score = token_similarity(
        str(first.get("title", "")), str(second.get("title", ""))
    )
    score = max(title_score, token_score)
    shared_tags = sorted(
        {str(tag) for tag in first.get("tags") or []}.intersection(
            {str(tag) for tag in second.get("tags") or []}
        )
    )
    has_stale_signal = is_redundancy_candidate(first, today) or is_redundancy_candidate(
        second, today
    )

    if score < 0.72:
        return None
    if not has_stale_signal and not shared_tags and score < 0.86:
        return None

    reasons: list[str] = [f"title similarity {score:.2f}"]
    if shared_tags:
        reasons.append("shared " + ", ".join(f"#{tag}" for tag in shared_tags))
    if has_stale_signal:
        reasons.append("old or overdue")
    return DedupCandidate(first, second, score, "; ".join(reasons))


def title_similarity(first: str, second: str) -> float:
    return SequenceMatcher(
        None, normalize_title(first), normalize_title(second)
    ).ratio()


def token_similarity(first: str, second: str) -> float:
    first_tokens = title_tokens(first)
    second_tokens = title_tokens(second)
    if not first_tokens or not second_tokens:
        return 0.0
    return len(first_tokens.intersection(second_tokens)) / len(
        first_tokens.union(second_tokens)
    )


def normalize_title(title: str) -> str:
    return " ".join(title_terms(title))


def title_tokens(title: str) -> set[str]:
    return set(title_terms(title))


def title_terms(title: str) -> list[str]:
    return [
        token
        for token in "".join(
            character.lower() if character.isalnum() else " " for character in title
        ).split()
        if len(token) > 2 and token not in STOPWORDS
    ]
