from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request


class DeliveryError(RuntimeError):
    """Raised when a requested digest delivery target cannot be used."""


def deliver_digest(*, title: str, message: str, target: str) -> list[str]:
    if target == "desktop":
        send_desktop_notification(title, message)
        return ["desktop"]
    if target == "telegram":
        send_telegram_message(message)
        return ["telegram"]
    if target == "both":
        send_desktop_notification(title, message)
        send_telegram_message(message)
        return ["desktop", "telegram"]
    raise DeliveryError(f"unknown delivery target: {target}")


def send_desktop_notification(title: str, message: str) -> None:
    system = platform.system()
    if system == "Linux":
        notify_send = shutil.which("notify-send")
        if not notify_send:
            raise DeliveryError("notify-send is not available for desktop delivery")
        subprocess.run([notify_send, title, message], check=True)
        return

    if system == "Darwin":
        osascript = shutil.which("osascript")
        if not osascript:
            raise DeliveryError("osascript is not available for desktop delivery")
        script = (
            f"display notification {json.dumps(message)} with title {json.dumps(title)}"
        )
        subprocess.run([osascript, "-e", script], check=True)
        return

    raise DeliveryError(f"desktop delivery is not supported on {system}")


def send_telegram_message(message: str) -> None:
    token = os.environ.get("OPENFIN_TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("OPENFIN_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise DeliveryError(
            "telegram delivery requires OPENFIN_TELEGRAM_BOT_TOKEN and OPENFIN_TELEGRAM_CHAT_ID"
        )

    data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status >= 400:
                raise DeliveryError("telegram delivery failed")
    except urllib.error.URLError as exc:
        raise DeliveryError(f"telegram delivery failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise DeliveryError("telegram delivery timed out") from exc
