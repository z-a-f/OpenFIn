from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import typer

from openfin.digest import normalize_delivery_target
from openfin.storage import OpenFinStore, write_text_atomic
from openfin.ui import console


ScheduleTarget = Literal["auto", "cron", "systemd", "launchd"]

OPENFIN_CRON_BEGIN = "# OPENFIN_DIGEST_BEGIN"
OPENFIN_CRON_END = "# OPENFIN_DIGEST_END"

schedule_app = typer.Typer(help="Manage scheduled digest reminders.")


@dataclass(frozen=True)
class ScheduleSpec:
    target: Literal["cron", "systemd", "launchd"]
    send: str
    morning: str
    evening: str
    root: Path
    python_executable: str


@schedule_app.command("show")
def show_schedule(
    target: str = typer.Option(
        "auto",
        "--target",
        help="Scheduler backend to preview: auto, cron, systemd, or launchd.",
    ),
    send: str = typer.Option(
        "desktop",
        "--send",
        help="Delivery target for scheduled digests: desktop, telegram, both, or none.",
    ),
    morning: str = typer.Option(
        "09:00",
        "--morning",
        help="Morning digest time in 24-hour HH:MM format.",
    ),
    evening: str = typer.Option(
        "17:30",
        "--evening",
        help="Evening digest time in 24-hour HH:MM format.",
    ),
) -> None:
    """Show the schedule that would be installed."""
    spec = build_schedule_spec(
        target=target, send=send, morning=morning, evening=evening
    )
    console.print(render_schedule(spec), markup=False)


@schedule_app.command("install")
def install_schedule(
    target: str = typer.Option(
        "auto",
        "--target",
        help="Scheduler backend to install: auto, cron, systemd, or launchd.",
    ),
    send: str = typer.Option(
        "desktop",
        "--send",
        help="Delivery target for scheduled digests: desktop, telegram, both, or none.",
    ),
    morning: str = typer.Option(
        "09:00",
        "--morning",
        help="Morning digest time in 24-hour HH:MM format.",
    ),
    evening: str = typer.Option(
        "17:30",
        "--evening",
        help="Evening digest time in 24-hour HH:MM format.",
    ),
) -> None:
    """Install scheduled morning and evening digests."""
    spec = build_schedule_spec(
        target=target, send=send, morning=morning, evening=evening
    )
    if spec.target == "cron":
        install_cron(spec)
    elif spec.target == "systemd":
        install_systemd(spec)
    else:
        install_launchd(spec)
    console.print(f"Installed OpenFin digest schedule using {spec.target}.")


@schedule_app.command("uninstall")
def uninstall_schedule(
    target: str = typer.Option(
        "auto",
        "--target",
        help="Scheduler backend to remove from: auto, cron, systemd, or launchd.",
    ),
) -> None:
    """Remove scheduled OpenFin digest reminders."""
    spec = build_schedule_spec(
        target=target, send="desktop", morning="09:00", evening="17:30"
    )
    if spec.target == "cron":
        uninstall_cron()
    elif spec.target == "systemd":
        uninstall_systemd()
    else:
        uninstall_launchd()
    console.print(f"Removed OpenFin digest schedule from {spec.target}.")


def build_schedule_spec(
    *,
    target: str,
    send: str,
    morning: str,
    evening: str,
) -> ScheduleSpec:
    return ScheduleSpec(
        target=resolve_target(target),
        send=normalize_delivery_target(send),
        morning=validate_time(morning),
        evening=validate_time(evening),
        root=OpenFinStore.from_env().root.expanduser(),
        python_executable=sys.executable,
    )


def resolve_target(target: str) -> Literal["cron", "systemd", "launchd"]:
    normalized = target.lower()
    if normalized == "auto":
        system = platform.system()
        if system == "Darwin":
            return "launchd"
        if system == "Linux" and shutil.which("systemctl"):
            return "systemd"
        return "cron"
    if normalized in {"cron", "systemd", "launchd"}:
        return normalized
    raise typer.BadParameter("schedule target must be auto, cron, systemd, or launchd")


def validate_time(value: str) -> str:
    pieces = value.split(":")
    if len(pieces) != 2:
        raise typer.BadParameter("time must use HH:MM")
    try:
        hour = int(pieces[0])
        minute = int(pieces[1])
    except ValueError as exc:
        raise typer.BadParameter("time must use HH:MM") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise typer.BadParameter("time must use HH:MM")
    return f"{hour:02d}:{minute:02d}"


def render_schedule(spec: ScheduleSpec) -> str:
    if spec.target == "cron":
        return render_cron_block(spec)
    if spec.target == "systemd":
        files = systemd_files(spec)
        return "\n\n".join(f"{path}\n{text}" for path, text in files.items())
    files = launchd_files(spec)
    return "\n\n".join(f"{path}\n{text}" for path, text in files.items())


def digest_command(spec: ScheduleSpec, kind: str) -> list[str]:
    return [
        spec.python_executable,
        "-m",
        "openfin",
        "digest",
        kind,
        "--send",
        spec.send,
    ]


def cron_line(spec: ScheduleSpec, kind: str, time_value: str) -> str:
    hour, minute = time_value.split(":")
    env = f"OPENFIN_HOME={shlex.quote(str(spec.root))}"
    command = " ".join(shlex.quote(part) for part in digest_command(spec, kind))
    return f"{minute} {hour} * * * {env} {command}"


def render_cron_block(spec: ScheduleSpec) -> str:
    return "\n".join(
        [
            OPENFIN_CRON_BEGIN,
            cron_line(spec, "morning", spec.morning),
            cron_line(spec, "evening", spec.evening),
            OPENFIN_CRON_END,
        ]
    )


def read_existing_crontab() -> str:
    crontab = shutil.which("crontab")
    if not crontab:
        raise typer.BadParameter("crontab is not available")
    result = subprocess.run(
        [crontab, "-l"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0 and "no crontab" not in result.stderr.lower():
        raise typer.BadParameter("could not read existing crontab")
    return result.stdout


def install_cron(spec: ScheduleSpec) -> None:
    crontab = shutil.which("crontab")
    if not crontab:
        raise typer.BadParameter("crontab is not available")
    existing = remove_cron_block(read_existing_crontab()).rstrip()
    block = render_cron_block(spec)
    updated = f"{existing}\n\n{block}\n" if existing else f"{block}\n"
    subprocess.run([crontab, "-"], input=updated, text=True, check=True)


def uninstall_cron() -> None:
    crontab = shutil.which("crontab")
    if not crontab:
        raise typer.BadParameter("crontab is not available")
    updated = remove_cron_block(read_existing_crontab()).rstrip()
    subprocess.run(
        [crontab, "-"], input=f"{updated}\n" if updated else "", text=True, check=True
    )


def remove_cron_block(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    skipping = False
    for line in lines:
        if line.strip() == OPENFIN_CRON_BEGIN:
            skipping = True
            continue
        if line.strip() == OPENFIN_CRON_END:
            skipping = False
            continue
        if not skipping:
            output.append(line)
    return "\n".join(output)


def systemd_user_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def systemd_files(spec: ScheduleSpec) -> dict[Path, str]:
    files: dict[Path, str] = {}
    for kind, time_value in {"morning": spec.morning, "evening": spec.evening}.items():
        command = " ".join(shlex.quote(part) for part in digest_command(spec, kind))
        service_name = f"openfin-digest-{kind}.service"
        timer_name = f"openfin-digest-{kind}.timer"
        files[systemd_user_dir() / service_name] = (
            "[Unit]\n"
            f"Description=OpenFin {kind} digest\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"Environment=OPENFIN_HOME={shlex.quote(str(spec.root))}\n"
            f"ExecStart={command}\n"
        )
        files[systemd_user_dir() / timer_name] = (
            "[Unit]\n"
            f"Description=OpenFin {kind} digest timer\n\n"
            "[Timer]\n"
            f"OnCalendar=*-*-* {time_value}:00\n"
            "Persistent=true\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        )
    return files


def install_systemd(spec: ScheduleSpec) -> None:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise typer.BadParameter("systemctl is not available")
    for path, text in systemd_files(spec).items():
        write_text_atomic(path, text)
    subprocess.run([systemctl, "--user", "daemon-reload"], check=True)
    for kind in ("morning", "evening"):
        subprocess.run(
            [systemctl, "--user", "enable", "--now", f"openfin-digest-{kind}.timer"],
            check=True,
        )


def uninstall_systemd() -> None:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise typer.BadParameter("systemctl is not available")
    for kind in ("morning", "evening"):
        subprocess.run(
            [systemctl, "--user", "disable", "--now", f"openfin-digest-{kind}.timer"],
            check=False,
        )
    for path in systemd_user_dir().glob("openfin-digest-*.*"):
        path.unlink()
    subprocess.run([systemctl, "--user", "daemon-reload"], check=True)


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def launchd_files(spec: ScheduleSpec) -> dict[Path, str]:
    files: dict[Path, str] = {}
    for kind, time_value in {"morning": spec.morning, "evening": spec.evening}.items():
        hour, minute = time_value.split(":")
        label = f"com.openfin.digest.{kind}"
        args = "\n".join(
            f"    <string>{escape_xml(part)}</string>"
            for part in digest_command(spec, kind)
        )
        files[launch_agents_dir() / f"{label}.plist"] = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n'
            "<dict>\n"
            "  <key>Label</key>\n"
            f"  <string>{label}</string>\n"
            "  <key>ProgramArguments</key>\n"
            "  <array>\n"
            f"{args}\n"
            "  </array>\n"
            "  <key>EnvironmentVariables</key>\n"
            "  <dict>\n"
            "    <key>OPENFIN_HOME</key>\n"
            f"    <string>{escape_xml(str(spec.root))}</string>\n"
            "  </dict>\n"
            "  <key>StartCalendarInterval</key>\n"
            "  <dict>\n"
            "    <key>Hour</key>\n"
            f"    <integer>{int(hour)}</integer>\n"
            "    <key>Minute</key>\n"
            f"    <integer>{int(minute)}</integer>\n"
            "  </dict>\n"
            "</dict>\n"
            "</plist>\n"
        )
    return files


def install_launchd(spec: ScheduleSpec) -> None:
    launchctl = shutil.which("launchctl")
    if not launchctl:
        raise typer.BadParameter("launchctl is not available")
    for path, text in launchd_files(spec).items():
        write_text_atomic(path, text)
        subprocess.run([launchctl, "load", "-w", str(path)], check=True)


def uninstall_launchd() -> None:
    launchctl = shutil.which("launchctl")
    if not launchctl:
        raise typer.BadParameter("launchctl is not available")
    for path in launch_agents_dir().glob("com.openfin.digest.*.plist"):
        subprocess.run([launchctl, "unload", "-w", str(path)], check=False)
        path.unlink()


def escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
