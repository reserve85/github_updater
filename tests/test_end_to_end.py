"""End-to-end offline integration test of the whole updater system.

This proves the REAL chain end to end (offline, no network):

1. a fake "installed exe" and a fake "downloaded new exe" are created on disk,
2. a CHILD python process simulates the frozen app: it sets ``sys.frozen`` and
   ``sys.executable``, calls the real ``UpdateService.apply_update()`` on the
   downloaded file, then ``restart_app()`` which really calls ``os._exit(0)``,
3. the detached helper (real ``cmd /c .bat`` launched without a window) waits
   for the child PID to exit, then performs the atomic swap,
4. the parent asserts the exe was replaced by the downloaded content, ``.new``
   is gone, ``.update.log`` records "Update complete", no ``.old`` is ever left
   behind, and the temporary ``.bat`` helper is cleaned up.

Only Windows + the installed package are needed; skipped elsewhere.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from github_updater import windows_updater as mod

on_windows = pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")

# Child code: simulate the frozen app, apply for real, then really exit.
# Invoked as: python -c CODE <downloaded> <installed>
_CHILD_CODE = r"""
import sys
from pathlib import Path

# simulate the frozen app
sys.frozen = True
sys.executable = sys.argv[2]

from github_updater import UpdateService

svc = UpdateService(
    current_version="1.2.0",
    owner="reserve85",
    repo="DummyRepo",
    app_name=Path(sys.argv[2]).stem,
)
ok = svc.apply_update(sys.argv[1])
sys.stdout.write(f"APPLY_RET={ok}\n")
sys.stdout.flush()
if ok:
    svc.restart_app()  # really exits the process, like a packaged app
sys.exit(1)  # pragma: no cover - unreachable when apply succeeded
"""


def _write_exe(path: Path, marker: bytes) -> None:
    """Plausible PE file: MZ header + padding (validation requires >= 1 MB)."""
    path.write_bytes(marker + b"\x00" * (mod.MIN_EXE_SIZE + 50_000))


@on_windows
class TestEndToEndFlow:
    def test_full_offline_apply_chain(self, tmp_path):
        install = tmp_path / "install"
        install.mkdir()
        installed = install / "FrozenApp.exe"
        _write_exe(installed, b"MZOLD")

        dl = tmp_path / "dl"
        dl.mkdir()
        downloaded = dl / "FrozenApp.exe"
        _write_exe(downloaded, b"MZNEW")

        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _CHILD_CODE,
                str(downloaded),
                str(installed),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(tmp_path),
        )
        out, err = proc.communicate(timeout=60)
        assert "APPLY_RET=True" in out, f"child failed: {out} {err}"

        # The helper replaces the exe after the child exits; poll until the
        # NEW content appears (sizes are identical, so poll on the marker).
        deadline = time.time() + 30
        while time.time() < deadline:
            if installed.exists() and installed.read_bytes().startswith(b"MZNEW"):
                break
            time.sleep(0.5)
        else:
            pytest.fail("update swap did not complete in time")

        # 1) the installed exe was REPLACED by the downloaded content
        assert installed.exists(), "installed exe missing after update"
        assert installed.read_bytes() == downloaded.read_bytes()
        assert installed.read_bytes()[:2] == b"MZ"

        # 2) the staged copy was consumed
        assert not (install / "FrozenApp.exe.new").exists(), ".new must be removed"

        # 3) no .old backup was ever left behind (stage-first design)
        assert not (install / "FrozenApp.exe.old").exists(), ".old must never appear"

        # 4) the .update.log records the successful swap
        log = install / "FrozenApp.exe.update.log"
        assert log.exists(), "update log missing"
        assert "Update complete" in log.read_text()

        # 5) temp helper (bat) was cleaned up; no NEW vbs is left behind
        temp = Path(__import__("tempfile").gettempdir())
        assert not (temp / "frozenapp_update.bat").exists()
