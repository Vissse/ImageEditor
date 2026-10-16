"""Self-update from GitHub Releases, like OmniDesk: ask the API for the latest
release, compare it with CURRENT_VERSION, download the installer asset and run
it silently - Inno Setup closes the app, upgrades it in place and relaunches.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from core.config import CURRENT_VERSION, GITHUB_USER, REPO_NAME, UPDATE_CHECK_TIMEOUT

API_URL = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/releases/latest"
_HEADERS = {
    "User-Agent": f"{REPO_NAME}/{CURRENT_VERSION}",
    "Accept": "application/vnd.github+json",
}


@dataclass
class UpdateInfo:
    version: str
    url: str
    size: int


def parse_version(text: str) -> tuple[int, ...]:
    numbers = [int(n) for n in re.findall(r"\d+", text.strip().lstrip("vV").split("-")[0])]
    return tuple(numbers) or (0,)


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def can_self_update() -> bool:
    # Only a frozen exe may replace itself; from source that would hit python.exe.
    return bool(getattr(sys, "frozen", False))


def fetch_latest_release(url: str | None = None) -> UpdateInfo | None:
    """Returns the newer release's info, or None when already up to date.
    Raises RuntimeError with a readable message when the check fails."""
    request = urllib.request.Request(url or API_URL, headers=_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=UPDATE_CHECK_TIMEOUT) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            raise RuntimeError("Vydání nejsou veřejně dostupná") from exc
        raise RuntimeError(f"Server vrátil chybu {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError("Nelze se připojit k serveru") from exc

    tag = str(data.get("tag_name", ""))
    if not is_newer(tag, CURRENT_VERSION):
        return None
    for asset in data.get("assets", []):
        name = str(asset.get("name", "")).lower()
        if name.endswith(".exe") and "setup" in name:
            return UpdateInfo(tag.lstrip("vV"), asset["browser_download_url"], int(asset.get("size", 0)))
    return None


class UpdateCheckWorker(QThread):
    # (UpdateInfo | None, error message)
    result = Signal(object, str)

    def __init__(self, url: str | None = None):
        super().__init__()
        self._url = url

    def run(self) -> None:
        try:
            self.result.emit(fetch_latest_release(self._url), "")
        except RuntimeError as exc:
            self.result.emit(None, str(exc))


class DownloadWorker(QThread):
    progress = Signal(int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, url: str, total_size: int = 0):
        super().__init__()
        self._url = url
        self._total = total_size

    def run(self) -> None:
        handle, target = tempfile.mkstemp(prefix="LibrionZonerPlus_update_", suffix=".exe")
        os.close(handle)
        try:
            request = urllib.request.Request(self._url, headers=_HEADERS)
            with urllib.request.urlopen(request, timeout=15) as response, open(target, "wb") as out:
                total = self._total or int(response.headers.get("Content-Length") or 0)
                done, last = 0, -1
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        percent = min(100, done * 100 // total)
                        if percent != last:
                            last = percent
                            self.progress.emit(percent)
            self.progress.emit(100)
            self.finished_ok.emit(target)
        except Exception as exc:  # noqa: BLE001
            try:
                os.remove(target)
            except OSError:
                pass
            self.failed.emit(str(exc))


def run_installer(installer_path: str) -> None:
    """Starts the downloaded installer silently and detached. The caller must
    quit the application right after this returns so the files can be replaced."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [installer_path, "/SILENT", "/SUPPRESSMSGBOXES", "/NOCANCEL", "/CLOSEAPPLICATIONS"],
        creationflags=flags,
        close_fds=True,
    )
