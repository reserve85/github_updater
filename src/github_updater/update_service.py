"""Service for checking and applying updates from GitHub.

Standalone module — the only dependency is the Python standard library.
Pass ``current_version`` to the constructor from wherever your app
keeps its version string.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"


class UpdateService:
    """Check for updates and download new versions from GitHub."""

    def __init__(
        self,
        current_version: str,
        owner: str,
        repo: str,
        app_name: str,
    ):
        self.current_version = current_version
        self.owner = owner
        self.repo = repo
        # Sanitize app_name for use in file names
        self._app_name = re.sub(r"[^a-zA-Z0-9]", "", app_name).lower()

    def check_for_update(self, token: str = "") -> dict:
        """Check if a new version is available.

        Works without a token for public repositories (anonymous API call).

        Returns:
            Dict with: has_update, latest_version, download_url, release_notes, error
        """
        result: dict = {
            "has_update": False,
            "latest_version": "",
            "download_url": "",
            "release_notes": "",
            "error": "",
        }

        url = GITHUB_API.format(owner=self.owner, repo=self.repo)
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": self._app_name,
        }
        if token:
            if token.startswith("github_pat"):
                headers["Authorization"] = f"Bearer {token}"
            else:
                headers["Authorization"] = f"token {token}"

        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())

            tag = data.get("tag_name", "")
            latest = tag.lstrip("v")
            result["latest_version"] = latest
            result["release_notes"] = data.get("body", "")

            if self._is_newer(latest, self.current_version):
                result["has_update"] = True
                for asset in data.get("assets", []):
                    if asset.get("name", "").endswith(".exe"):
                        result["download_url"] = asset.get("url", "")
                        break
                if not result["download_url"]:
                    for asset in data.get("assets", []):
                        if asset.get("name", "").endswith(".zip"):
                            result["download_url"] = asset.get("url", "")
                            break
                if not result["download_url"]:
                    result["download_url"] = data.get("zipball_url", "")

        except URLError as e:
            result["error"] = f"Network error: {e.reason}"
        except Exception as e:
            result["error"] = str(e)

        return result

    def download_update(self, download_url: str, token: str = "",
                        progress_callback=None) -> str:
        """Download the update to a temp file.

        Args:
            download_url: URL to download from.
            token: GitHub token for authentication.
            progress_callback: Optional callable(bytes_downloaded, total_size).

        Returns:
            Path to downloaded file, or empty string on failure.
        """
        headers = {
            "User-Agent": self._app_name,
            # Anonymous asset downloads from public repos also need the binary
            # Accept header, otherwise GitHub responds with release JSON.
            "Accept": "application/octet-stream",
        }
        if token:
            if token.startswith("github_pat"):
                headers["Authorization"] = f"Bearer {token}"
            else:
                headers["Authorization"] = f"token {token}"

        try:
            req = Request(download_url, headers=headers)
            with urlopen(req, timeout=120) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                logger.info("Downloading from %s (size: %d)", download_url, total_size)

                # Determine suffix from URL
                suffix = ".exe"
                if ".zip" in download_url:
                    suffix = ".zip"

                tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
                os.close(tmp_fd)

                downloaded = 0
                with open(tmp_path, "wb") as f:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            progress_callback(downloaded, total_size)

            if suffix in (".exe", ".bin"):
                with open(tmp_path, "rb") as f:
                    header = f.read(2)
                if header != b"MZ":
                    logger.warning("Downloaded file is not a valid exe (header: %s)", header)
                    os.unlink(tmp_path)
                    return ""

            logger.info("Downloaded %d bytes to %s", downloaded, tmp_path)
            return tmp_path
        except Exception as e:
            logger.exception("Download error: %s", e)
            return ""

    def apply_update(self, downloaded_path: str) -> bool:
        """Replace the current executable using a detached batch helper.

        The batch script waits for the running process to exit, then
        replaces the exe file.  On success the helper window closes
        immediately; on failure it stays open (and is brought to the
        foreground) so the user can see what went wrong.  The user
        restarts the app manually.
        """
        if not os.path.exists(downloaded_path):
            logger.error("Downloaded path does not exist: %s", downloaded_path)
            return False

        current_exe = sys.executable if getattr(sys, "frozen", False) else None
        if not current_exe:
            logger.error("Not running as frozen exe — cannot self-update")
            return False

        try:
            with open(downloaded_path, "rb") as f:
                if f.read(2) != b"MZ":
                    logger.error("Downloaded file is not a valid Windows executable")
                    return False
        except Exception:
            return False

        current_exe = os.path.abspath(current_exe)
        downloaded_path = os.path.abspath(downloaded_path)
        backup_path = current_exe + ".old"
        pid = os.getpid()

        try:
            # Backup current exe
            if os.path.exists(backup_path):
                os.unlink(backup_path)
            os.rename(current_exe, backup_path)

            bat_content = (
                "@echo off\r\n"
                f"echo Waiting for process {pid} to exit...\r\n"
                ":waitloop\r\n"
                f'tasklist /fi "PID eq {pid}" | find "{pid}" >nul\r\n'
                "if not errorlevel 1 (\r\n"
                "  waitfor /t 1 NothingThatWillEverExist >nul 2>&1\r\n"
                "  goto waitloop\r\n"
                ")\r\n"
                f'echo Replacing {self._app_name} executable...\r\n'
                "set tries=0\r\n"
                ":trycopy\r\n"
                "set /a tries+=1\r\n"
                "if %tries% gtr 5 goto giveup\r\n"
                f'copy /y "{downloaded_path}" "{current_exe}" >nul 2>&1\r\n'
                "if errorlevel 1 (\r\n"
                "  echo   Attempt %tries% failed, retrying...\r\n"
                "  waitfor /t 2 NothingThatWillEverExist >nul 2>&1\r\n"
                "  goto trycopy\r\n"
                ")\r\n"
                f'if exist "{current_exe}" goto cleanup\r\n'
                ":giveup\r\n"
                "echo.\r\n"
                "echo UPDATE FAILED - restoring original executable...\r\n"
                f'move /y "{backup_path}" "{current_exe}" >nul 2>&1\r\n'
                "if errorlevel 1 echo   WARNING: could not restore the original executable!\r\n"
                "echo.\r\n"
                "echo The update did not complete. Window stays open - read what happened.\r\n"
                f'title {self._app_name} Update Failed\r\n'
                f'>nul 2>&1 powershell -NoProfile -Command "$w = New-Object ' +
                f'-ComObject WScript.Shell; $w.AppActivate(\'{self._app_name} Update Failed\')"\r\n'
                "echo Press any key to close this window ...\r\n"
                "pause >nul\r\n"
                "goto end\r\n"
                ":cleanup\r\n"
                "echo.\r\n"
                "echo Update complete! You can now start the new version.\r\n"
                f'del /f /q "{backup_path}" >nul 2>&1\r\n'
                f'del /f /q "{downloaded_path}" >nul 2>&1\r\n'
                ":end\r\n"
                'del /f /q "%~f0"\r\n'
            )

            bat_path = os.path.join(tempfile.gettempdir(), f"{self._app_name}_update.bat")
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat_content)

            logger.info("Update batch script written to %s", bat_path)

            # Launch minimized via a tiny VBScript wrapper
            vbs_path = os.path.join(tempfile.gettempdir(), f"{self._app_name}_update.vbs")
            with open(vbs_path, "w", encoding="utf-8") as vf:
                vf.write(
                    f'Set objShell = CreateObject("WScript.Shell")\r\n'
                    f'objShell.Run "cmd /c ""{bat_path}""", 7, False\r\n'
                )

            subprocess.Popen(
                ["wscript.exe", vbs_path],
                close_fds=True,
                cwd=tempfile.gettempdir(),
            )
            return True
        except Exception as e:
            logger.exception("Update error: %s", e)
            return False

    def restart_app(self) -> None:
        """Exit the app — user manually restarts with the new exe."""
        logger.info("Exiting app for manual restart ...")
        os._exit(0)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def clean_old_files(exe_path: str | None = None) -> None:
        """Remove leftover ``.old`` backup files from a previous update."""
        if exe_path is None:
            exe_path = sys.executable if getattr(sys, "frozen", False) else ""
        if not exe_path:
            return
        old_path = exe_path + ".old"
        if os.path.exists(old_path):
            try:
                os.unlink(old_path)
                logger.info("Removed old backup: %s", old_path)
            except OSError as e:
                logger.debug("Could not remove old backup %s: %s", old_path, e)

    @staticmethod
    def _is_newer(latest: str, current: str) -> bool:
        """Compare version strings (e.g. '1.2.0' vs '1.1.9')."""
        try:
            latest_parts = [int(x) for x in latest.split(".")]
            current_parts = [int(x) for x in current.split(".")]
            return latest_parts > current_parts
        except (ValueError, AttributeError):
            return False
