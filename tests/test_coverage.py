from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from openfin import delivery, scheduler
from openfin import digest as digest_module
from openfin.cli import app
from openfin.storage import read_text, write_text_atomic


runner = CliRunner()


def openfin_home(tmp_path: Path) -> Path:
    return tmp_path / "openfin"


def run_cli(tmp_path: Path, args: list[str], *, input: str | None = None):
    return runner.invoke(
        app,
        args,
        env={"OPENFIN_HOME": str(openfin_home(tmp_path))},
        input=input,
    )


def load_tasks(tmp_path: Path) -> list[dict]:
    return yaml.safe_load(read_text(openfin_home(tmp_path) / "tasks.yaml"))


def log_text(tmp_path: Path) -> str:
    log_dir = openfin_home(tmp_path) / "log"
    return "\n".join(read_text(path) for path in log_dir.glob("*.md"))


def test_delivery_router_calls_requested_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        delivery,
        "send_desktop_notification",
        lambda title, message: calls.append(("desktop", title)),
    )
    monkeypatch.setattr(
        delivery,
        "send_telegram_message",
        lambda message: calls.append(("telegram", message)),
    )

    sent = delivery.deliver_digest(title="Digest", message="Hello", target="both")

    assert sent == ["desktop", "telegram"]
    assert calls == [("desktop", "Digest"), ("telegram", "Hello")]
    with pytest.raises(delivery.DeliveryError, match="unknown delivery target"):
        delivery.deliver_digest(title="Digest", message="Hello", target="sms")


def test_main_module_import_exposes_cli_app() -> None:
    import openfin.__main__ as main

    assert main.app is app


def test_desktop_delivery_linux_and_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(delivery.platform, "system", lambda: "Linux")
    monkeypatch.setattr(delivery.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        delivery.subprocess,
        "run",
        lambda command, check: calls.append(command),
    )

    delivery.send_desktop_notification("Title", "Body")

    assert calls[-1] == ["/bin/notify-send", "Title", "Body"]

    monkeypatch.setattr(delivery.platform, "system", lambda: "Darwin")
    delivery.send_desktop_notification("Title", 'Body "quoted"')

    assert calls[-1][0:2] == ["/bin/osascript", "-e"]
    assert "display notification" in calls[-1][2]
    assert "quoted" in calls[-1][2]


def test_desktop_delivery_reports_missing_or_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(delivery.platform, "system", lambda: "Linux")
    monkeypatch.setattr(delivery.shutil, "which", lambda name: None)

    with pytest.raises(delivery.DeliveryError, match="notify-send"):
        delivery.send_desktop_notification("Title", "Body")

    monkeypatch.setattr(delivery.platform, "system", lambda: "Windows")

    with pytest.raises(delivery.DeliveryError, match="not supported"):
        delivery.send_desktop_notification("Title", "Body")


class FakeTelegramResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self) -> "FakeTelegramResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


def test_telegram_delivery_success_and_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[tuple[str, bytes, str]] = []

    def fake_urlopen(request, timeout):
        opened.append((request.full_url, request.data, request.get_method()))
        return FakeTelegramResponse()

    monkeypatch.setenv("OPENFIN_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("OPENFIN_TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(delivery.urllib.request, "urlopen", fake_urlopen)

    delivery.send_telegram_message("Hello world")

    assert opened[0][0] == "https://api.telegram.org/bottoken/sendMessage"
    assert b"chat_id=chat" in opened[0][1]
    assert b"text=Hello+world" in opened[0][1]
    assert opened[0][2] == "POST"

    monkeypatch.delenv("OPENFIN_TELEGRAM_BOT_TOKEN")
    with pytest.raises(delivery.DeliveryError, match="OPENFIN_TELEGRAM_BOT_TOKEN"):
        delivery.send_telegram_message("Hello")

    monkeypatch.setenv("OPENFIN_TELEGRAM_BOT_TOKEN", "token")

    def failing_urlopen(request, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(delivery.urllib.request, "urlopen", failing_urlopen)
    with pytest.raises(delivery.DeliveryError, match="offline"):
        delivery.send_telegram_message("Hello")


def test_digest_delivery_success_and_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivered: list[tuple[str, str]] = []

    monkeypatch.setattr(
        digest_module,
        "deliver_digest",
        lambda *, title, message, target: delivered.append((title, target)) or [target],
    )

    sent = run_cli(tmp_path, ["digest", "morning", "--send", "desktop"])
    bad_kind = run_cli(tmp_path, ["digest", "midday"])
    bad_target = run_cli(tmp_path, ["digest", "morning", "--send", "email"])

    assert sent.exit_code == 0, sent.output
    assert "Sent digest via desktop." in sent.output
    assert delivered == [("OpenFin morning digest", "desktop")]
    assert bad_kind.exit_code != 0
    assert "digest kind must be morning or evening" in bad_kind.output
    assert bad_target.exit_code != 0
    assert (
        "delivery target must be none, desktop, telegram, or both" in bad_target.output
    )


def schedule_spec(tmp_path: Path, target: str = "cron") -> scheduler.ScheduleSpec:
    return scheduler.ScheduleSpec(
        target=target,
        send="desktop",
        morning="08:00",
        evening="18:30",
        root=tmp_path / "openfin home",
        python_executable="/usr/bin/python",
    )


def test_scheduler_target_resolution_and_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduler.platform, "system", lambda: "Darwin")
    assert scheduler.resolve_target("auto") == "launchd"

    monkeypatch.setattr(scheduler.platform, "system", lambda: "Linux")
    monkeypatch.setattr(scheduler.shutil, "which", lambda name: "/bin/systemctl")
    assert scheduler.resolve_target("auto") == "systemd"

    monkeypatch.setattr(scheduler.shutil, "which", lambda name: None)
    assert scheduler.resolve_target("auto") == "cron"
    assert scheduler.resolve_target("cron") == "cron"
    assert scheduler.validate_time("8:05") == "08:05"

    with pytest.raises(Exception, match="time must use HH:MM"):
        scheduler.validate_time("25:00")
    with pytest.raises(Exception, match="schedule target"):
        scheduler.resolve_target("windows-task")


def test_scheduler_commands_route_to_selected_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setenv("OPENFIN_HOME", str(openfin_home(tmp_path)))
    monkeypatch.setattr(
        scheduler, "install_cron", lambda spec: calls.append(f"install {spec.target}")
    )
    monkeypatch.setattr(
        scheduler, "uninstall_cron", lambda: calls.append("uninstall cron")
    )

    scheduler.install_schedule(
        target="cron", send="desktop", morning="08:00", evening="18:00"
    )
    scheduler.uninstall_schedule(target="cron")

    assert calls == ["install cron", "uninstall cron"]


def test_scheduler_renders_systemd_and_launchd_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduler, "systemd_user_dir", lambda: tmp_path / "systemd")
    monkeypatch.setattr(scheduler, "launch_agents_dir", lambda: tmp_path / "launchd")

    systemd = scheduler.render_schedule(schedule_spec(tmp_path, "systemd"))
    launchd = scheduler.render_schedule(schedule_spec(tmp_path, "launchd"))

    assert "openfin-digest-morning.service" in systemd
    assert "OnCalendar=*-*-* 08:00:00" in systemd
    assert "OPENFIN_HOME=" in systemd
    assert "com.openfin.digest.morning" in launchd
    assert "<integer>8</integer>" in launchd
    assert "&amp;" in scheduler.escape_xml("a&b")


def test_cron_install_and_uninstall_are_marker_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = schedule_spec(tmp_path, "cron")
    crontab_text = "0 7 * * * echo keep\n"
    writes: list[str] = []

    def fake_run(command, **kwargs):
        nonlocal crontab_text
        if command == ["/usr/bin/crontab", "-l"]:
            return subprocess.CompletedProcess(
                command, 0, stdout=crontab_text, stderr=""
            )
        if command == ["/usr/bin/crontab", "-"]:
            crontab_text = kwargs["input"]
            writes.append(crontab_text)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(scheduler.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)

    scheduler.install_cron(spec)
    scheduler.uninstall_cron()

    assert "OPENFIN_DIGEST_BEGIN" in writes[0]
    assert "echo keep" in writes[0]
    assert "OPENFIN_DIGEST_BEGIN" not in writes[1]
    assert "echo keep" in writes[1]


def test_systemd_and_launchd_install_uninstall_are_openfin_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    systemd_dir = tmp_path / "systemd"
    launchd_dir = tmp_path / "launchd"
    systemd_dir.mkdir()
    launchd_dir.mkdir()
    write_text_atomic(systemd_dir / "openfin-digest-old.timer", "old")
    write_text_atomic(launchd_dir / "com.openfin.digest.old.plist", "old")
    calls: list[list[str]] = []

    monkeypatch.setattr(scheduler, "systemd_user_dir", lambda: systemd_dir)
    monkeypatch.setattr(scheduler, "launch_agents_dir", lambda: launchd_dir)
    monkeypatch.setattr(scheduler.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda command, check=True: calls.append(command),
    )

    scheduler.install_systemd(schedule_spec(tmp_path, "systemd"))
    scheduler.uninstall_systemd()
    scheduler.install_launchd(schedule_spec(tmp_path, "launchd"))
    scheduler.uninstall_launchd()

    assert any("enable" in command for command in calls)
    assert any("disable" in command for command in calls)
    assert any("load" in command for command in calls)
    assert any("unload" in command for command in calls)
    assert not list(systemd_dir.glob("openfin-digest-*.*"))
    assert not list(launchd_dir.glob("com.openfin.digest.*.plist"))


def test_review_decision_branches_update_tasks_and_log(tmp_path: Path) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    for title in ["Snooze me", "Block me", "Drop me", "Done me", "Unknown me"]:
        created = run_cli(tmp_path, ["add", title, "-d", yesterday])
        assert created.exit_code == 0, created.output

    reviewed = run_cli(
        tmp_path,
        ["review"],
        input=f"snooze\n{tomorrow}\nblock\nwaiting on Alex\ndrop\ndone\nlater\n",
    )

    assert reviewed.exit_code == 0, reviewed.output
    tasks = load_tasks(tmp_path)
    assert tasks[0]["due"] == tomorrow
    assert tasks[1]["status"] == "blocked"
    assert "waiting on Alex" in tasks[1]["notes"]
    assert tasks[2]["status"] == "dropped"
    assert tasks[3]["status"] == "done"
    assert tasks[4]["status"] == "open"
    assert "Skipped unknown decision: later" in reviewed.output
    text = log_text(tmp_path)
    assert "#dropped t-0003 Drop me" in text
    assert "#done t-0004 Done me" in text


def test_context_copy_budget_and_unknown_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    fake_pyperclip = type("FakePyperclip", (), {"copy": staticmethod(copied.append)})

    monkeypatch.setitem(sys.modules, "pyperclip", fake_pyperclip)

    created = run_cli(tmp_path, ["add", "Copy context task", "-t", "code"])
    assert created.exit_code == 0, created.output

    copied_context = run_cli(
        tmp_path, ["context", "default", "--copy", "--budget", "1"]
    )
    unknown = run_cli(tmp_path, ["context", "missing"])

    assert copied_context.exit_code == 0, copied_context.output
    assert copied
    assert "Copy context task" in copied[0]
    assert "Copied context pack to clipboard." in copied_context.output
    assert "Budget warning" in copied_context.output
    assert unknown.exit_code != 0
    assert "unknown profile: missing" in unknown.output


def test_triage_empty_decision_note_and_skip_branches(tmp_path: Path) -> None:
    empty = run_cli(tmp_path, ["triage"])
    assert empty.exit_code == 0, empty.output
    assert "Inbox is empty." in empty.output

    for text in ["capture decision", "capture note", "capture skip"]:
        captured = run_cli(tmp_path, ["in", text])
        assert captured.exit_code == 0, captured.output

    triaged = run_cli(tmp_path, ["triage"], input="decision\nnote\nskip\n")

    assert triaged.exit_code == 0, triaged.output
    text = log_text(tmp_path)
    inbox = read_text(openfin_home(tmp_path) / "inbox.md")
    assert "#decision capture decision" in text
    assert "#note capture note" in text
    assert "capture skip" in inbox


def test_review_commit_rejects_non_integer_recheck_days(tmp_path: Path) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    created = run_cli(tmp_path, ["add", "Bad commit days", "-d", yesterday])
    assert created.exit_code == 0, created.output

    reviewed = run_cli(tmp_path, ["review"], input="commit\nlater\n")

    assert reviewed.exit_code != 0
    assert "recheck days must be an integer" in reviewed.output


def test_task_edit_filters_block_drop_and_validation(tmp_path: Path) -> None:
    created = run_cli(tmp_path, ["add", "Edit me", "-t", "ops"])
    assert created.exit_code == 0, created.output

    edited = run_cli(
        tmp_path,
        [
            "edit",
            "t-0001",
            "--title",
            "Edited task",
            "-p",
            "P0",
            "-d",
            "tomorrow",
            "--status",
            "doing",
            "-t",
            "eng,ops",
            "--notes",
            "details",
        ],
    )
    listed = run_cli(tmp_path, ["ls", "--status", "doing", "--tag", "eng", "-p", "P0"])
    blocked = run_cli(tmp_path, ["block", "t-0001", "needs input"])
    dropped = run_cli(tmp_path, ["drop", "t-0001"])
    invalid_priority = run_cli(tmp_path, ["add", "Bad priority", "-p", "P9"])
    invalid_status = run_cli(tmp_path, ["ls", "--status", "sleeping"])
    missing = run_cli(tmp_path, ["done", "t-9999"])

    assert edited.exit_code == 0, edited.output
    assert listed.exit_code == 0, listed.output
    assert "Edited task" in listed.output
    assert blocked.exit_code == 0, blocked.output
    assert dropped.exit_code == 0, dropped.output
    assert invalid_priority.exit_code != 0
    assert invalid_status.exit_code != 0
    assert missing.exit_code != 0

    tasks = load_tasks(tmp_path)
    text = log_text(tmp_path)
    assert tasks[0]["status"] == "dropped"
    assert tasks[0]["tags"] == ["eng", "ops"]
    assert "#blocked t-0001 needs input" in text
    assert "#dropped t-0001 Edited task" in text


def test_edit_without_editor_prints_task_yaml(tmp_path: Path) -> None:
    created = run_cli(tmp_path, ["add", "Print editable YAML"])
    assert created.exit_code == 0, created.output

    edited = runner.invoke(
        app,
        ["edit", "t-0001"],
        env={"OPENFIN_HOME": str(openfin_home(tmp_path)), "EDITOR": ""},
    )

    assert edited.exit_code == 0
    assert "Print editable YAML" in edited.output
    assert "priority: P2" in edited.output


def test_edit_with_editor_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    created = run_cli(tmp_path, ["add", "Editor invalid YAML"])
    assert created.exit_code == 0, created.output

    editor = tmp_path / "editor.py"
    write_text_atomic(
        editor,
        "import pathlib, sys\npathlib.Path(sys.argv[1]).write_text('- nope\\n', encoding='utf-8')\n",
    )
    editor.chmod(0o755)

    edited = runner.invoke(
        app,
        ["edit", "t-0001"],
        env={
            "OPENFIN_HOME": str(openfin_home(tmp_path)),
            "EDITOR": f"{os.sys.executable} {editor}",
        },
    )

    assert edited.exit_code != 0
    assert "edited task must be a YAML mapping" in edited.output
