"""Windows EXE self-replacement with a stage-first, atomic-swap design.

The previous implementation renamed the running exe to ``.exe.old`` before the
new file was in place and hid every batch error behind ``>nul 2>&1`` - a failed
copy then left the user with ``.exe.old`` and no executable. This module fixes
that by:

* validating the download (size + ``MZ`` header) before touching anything,
* auto-restoring a broken v0.x state (only ``.exe.old`` present),
* proving the app folder is writable, then staging the new exe as ``<exe>.new``
  on the same volume,
* launching a detached helper that waits for the process to exit and retries
  the atomic ``move`` until the file lock clears; the ORIGINAL exe is only
  ever overwritten by the finished new file,
* writing an exact-CRLF ``.bat`` + ``.vbs`` (text mode produced ``\\r\\r\\n``
  which VBScript can't parse) and a real ``.update.log``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from github_updater.models import UpdateError

#: a real packaged exe is many MB; anything near-zero is a failed download
MIN_EXE_SIZE = 1_000_000
#: retries for the atomic move after the process exits (30 * 2 s = 60 s)
MOVE_RETRIES = 30
MOVE_RETRY_WAIT_SECONDS = 2
#: max seconds to wait for the old process to exit (30 * 1 s)
WAIT_FOR_EXIT_LIMIT = 30


def _current_exe() -> Path | None:
    """The running ``.exe`` in a frozen build, else ``None``."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve()
    if exe.suffix.lower() == ".exe" and exe.is_file():
        return exe
    return None


def validate_download(path: Path) -> None:
    """Raise :class:`UpdateError` for obviously broken downloads."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise UpdateError(f"Downloaded file not found: {path}") from exc
    if size < MIN_EXE_SIZE:
        raise UpdateError(
            f"Downloaded file is unexpectedly small ({size} bytes) - refusing to apply"
        )
    with path.open("rb") as fh:
        if fh.read(2) != b"MZ":
            raise UpdateError("Downloaded file is not a valid Windows executable")


def restore_old_state(exe: Path) -> None:
    """If a legacy updater left ``<exe>.old`` and the exe is missing, restore it."""
    backup = exe.with_name(exe.name + ".old")
    if not exe.is_file() and backup.is_file():
        try:
            backup.replace(exe)
        except OSError:
            raise UpdateError(f"Could not restore previous executable {backup}")


def write_probe(exe: Path) -> None:
    """Fail early with a clear message when the app folder is not writable."""
    probe = exe.with_name(exe.name + ".write_probe")
    try:
        probe.write_bytes(b"")
    except OSError as exc:
        raise UpdateError(
            f"App folder is not writable ({exe.parent}). "
            "Run the app as administrator or install it into a writable folder."
        ) from exc
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
def swap_bat_content(exe: Path, staged: Path, pid: int, log_path: Path) -> str:
    """The helper batch: wait for the process to exit, then swap ``.new`` -> exe.

    The original is never removed before the swap succeeds. Success closes the
    window immediately; failure keeps it open, logs the error to ``.update.log``
    and tells the user the current version is still in place.
    """
    r = "\r\n"
    return (
        "@echo off" + r
        + "setlocal EnableExtensions" + r
        + f'set "LOG={log_path}"' + r
        + 'echo [%date% %time%] Update helper started. > "%LOG%"' + r
        + "goto begin" + r
        + ":logmsg" + r
        + '>> "%LOG%" echo [%date% %time%] %*' + r
        + "echo %*" + r
        + "exit /b" + r
        + ":begin" + r
        + "" + r
        + f"call :logmsg Waiting for process {pid} to exit..." + r
        + "set waitloops=0" + r
        + ":waitloop" + r
        + "set /a waitloops+=1" + r
        + f"if %waitloops% gtr {WAIT_FOR_EXIT_LIMIT} goto postwait" + r
        + f'tasklist /fi "PID eq {pid}" | find "{pid}" >nul 2>&1' + r
        + "if not errorlevel 1 (" + r
        + "  waitfor /t 1 NothingThatWillEverExist >nul 2>&1" + r
        + "  goto waitloop" + r
        + ")" + r
        + ":postwait" + r
        + f"call :logmsg Replacing {exe.name} with {staged.name} ..." + r
        + "set tries=0" + r
        + ":trymove" + r
        + "set /a tries+=1" + r
        + f"if %tries% gtr {MOVE_RETRIES} goto failed" + r
        + f'move /y "{staged}" "{exe}" >nul 2>&1' + r
        + "if errorlevel 1 (" + r
        + "  call :logmsg   File still locked, retrying..." + r
        + f"  waitfor /t {MOVE_RETRY_WAIT_SECONDS} NothingThatWillEverExist >nul 2>&1" + r
        + "  goto trymove" + r
        + ")" + r
        + f'if not exist "{exe}" goto failed' + r
        + "call :logmsg Update complete - you can now start the new version." + r
        + f'del /q "{staged}" >nul 2>&1' + r
        + "goto end" + r
        + ":failed" + r
        + "echo." + r
        + "call :logmsg UPDATE FAILED - your current version is still in place." + r
        + f"call :logmsg Log written to \"{log_path}\"." + r
        + "echo Press any key to close this window ..." + r
        + "pause >nul" + r
        + ":end" + r
        # self-delete via a detached process: deleting "%~f0" inline makes cmd
        # exit nonzero with "The batch file cannot be found."
        + 'start "" /b cmd /c "del /q ""%~f0"" >nul 2>&1"' + r
        + "exit /b 0" + r
    )


def build_launcher_vbs(bat_path: Path) -> str:
    """VBS that runs the batch minimized via ``wscript.exe``."""
    return (
        "Set objShell = CreateObject(\"WScript.Shell\")\r\n"
        f'objShell.Run "cmd /c ""{bat_path}"", 7, False\r\n'
    )


def launch_helper(batch: Path, app_key: str) -> bool:
    """Launch the batch minimized through ``wscript.exe`` (detached)."""
    vbs = Path(tempfile.gettempdir()) / f"{app_key}_update.vbs"
    # write_bytes keeps the CRLF exact - text mode would turn \r\n into \r\r\n
    vbs.write_bytes(build_launcher_vbs(batch).encode("utf-8"))
    try:
        subprocess.Popen(
            ["wscript.exe", str(vbs)],
            close_fds=True,
            cwd=str(Path(tempfile.gettempdir())),
        )
        return True
    except OSError as exc:
        raise UpdateError(f"Could not launch update helper: {exc}") from exc
def apply_update(downloaded_path: str) -> bool:
    """Validate, stage and launch a safe self-replacement.

    Returns ``True`` once the detached helper is running. Raises
    :class:`UpdateError` on any preventable failure so the caller can inform
    the user.
    """
    exe = _current_exe()
    if exe is None:
        raise UpdateError("Apply is only supported in the packaged build")

    downloaded = Path(downloaded_path)
    validate_download(downloaded)
    restore_old_state(exe)
    write_probe(exe)

    staged = exe.with_name(exe.name + ".new")
    try:
        shutil.copy2(downloaded, staged)
    except OSError as exc:
        raise UpdateError(f"Could not stage the new version: {exc}") from exc

    log_path = exe.with_name(exe.name + ".update.log")
    batch_path = Path(tempfile.gettempdir()) / f"{exe.stem.lower()}_update.bat"
    # write_bytes keeps the CRLF exact; text mode would emit \r\r\n
    batch_path.write_bytes(
        swap_bat_content(exe, staged, os.getpid(), log_path).encode("utf-8")
    )

    if not launch_helper(batch_path, exe.stem.lower()):
        try:
            staged.unlink()
        except OSError:
            pass
        raise UpdateError("Could not launch the update helper")
    return True


def clean_old_files(exe_path: str | Path | None = None) -> None:
    """Restore a broken v0.x state, then remove leftover stages.

    ``exe_path`` mirrors the historical static ``UpdateService.clean_old_files``
    signature; when omitted (or empty) the running frozen exe is used.
    """
    if exe_path in (None, ""):
        exe = _current_exe()
    else:
        exe = Path(exe_path)
    if exe is None:
        return
    try:
        restore_old_state(exe)
    except UpdateError:
        pass  # best-effort at startup; do not block the app launch
    for leftover in (
        exe.with_name(exe.name + ".old"),
        exe.with_name(exe.name + ".new"),
        exe.with_name(exe.name + ".update.log"),
    ):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            pass
