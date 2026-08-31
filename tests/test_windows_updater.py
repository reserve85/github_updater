"""Tests for github_updater.windows_updater - the SAFE EXE replacement.

Covers validation, staging, exact-CRLF helper files, recovery of a broken
v0.x state, and - on Windows - a REAL ``cmd /c`` swap that proves the batch
actually replaces the exe atomically without leaving only ``.old``.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from github_updater import windows_updater as mod
from github_updater.models import UpdateError

on_windows = pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")


def _fake_exe(tmp_path: Path, name: str = "GasmeterDownloader.exe") -> Path:
    # > MIN_EXE_SIZE so validate_download passes
    exe = tmp_path / name
    exe.write_bytes(b"MZ" + b"\x00" * (mod.MIN_EXE_SIZE + 100))
    return exe


def _fake_download(tmp_path: Path) -> Path:
    # > MIN_EXE_SIZE so validate_download passes
    download = tmp_path / "update_download.exe"
    download.write_bytes(b"MZ" + b"NEW" * (mod.MIN_EXE_SIZE // 3 + 100))
    return download


class TestValidateDownload:
    def test_missing_raises(self, tmp_path):
        with pytest.raises(UpdateError, match="not found"):
            mod.validate_download(tmp_path / "nope.exe")

    def test_small_raises(self, tmp_path):
        t = tmp_path / "small.exe"
        t.write_bytes(b"MZ")
        with pytest.raises(UpdateError, match="unexpectedly small"):
            mod.validate_download(t)

    def test_not_pe_raises(self, tmp_path):
        t = tmp_path / "bad.exe"
        t.write_bytes(b"\x00" * (mod.MIN_EXE_SIZE + 1))
        with pytest.raises(UpdateError, match="not a valid Windows executable"):
            mod.validate_download(t)

    def test_valid_passes(self, tmp_path):
        t = tmp_path / "ok.exe"
        t.write_bytes(b"MZ" + b"\x00" * mod.MIN_EXE_SIZE)
        mod.validate_download(t)  # no raise


class TestRestoreOldState:
    def test_restores_when_exe_missing(self, tmp_path):
        exe = tmp_path / "app.exe"
        backup = tmp_path / "app.exe.old"
        backup.write_bytes(b"MZ-old-backup")
        mod.restore_old_state(exe)
        assert exe.is_file()
        assert exe.read_bytes() == b"MZ-old-backup"
        assert not backup.exists()

    def test_does_nothing_when_exe_present(self, tmp_path):
        exe = _fake_exe(tmp_path)
        original = exe.read_bytes()
        (tmp_path / "app.exe.old").write_bytes(b"stale")
        mod.restore_old_state(exe)
        assert exe.read_bytes() == original  # untouched

    def test_no_old_no_exe_no_error(self, tmp_path):
        mod.restore_old_state(tmp_path / "missing.exe")


class TestWriteProbe:
    def test_writable_creates_then_removes_probe(self, tmp_path):
        exe = _fake_exe(tmp_path)
        mod.write_probe(exe)
        assert not (tmp_path / "app.exe.write_probe").exists()

    def test_not_writable_raises(self, tmp_path, monkeypatch):
        exe = _fake_exe(tmp_path)

        def deny(_path, _data, **_kw):
            raise PermissionError("denied")

        monkeypatch.setattr(Path, "write_bytes", deny)
        with pytest.raises(UpdateError, match="not writable"):
            mod.write_probe(exe)
class TestSwapBatContent:
    def test_waits_for_pid_and_uses_find(self, tmp_path):
        exe = _fake_exe(tmp_path)
        log = exe.with_name("app.exe.update.log")
        content = mod.swap_bat_content(exe, tmp_path / "app.exe.new", 12345, log)
        assert "PID eq 12345" in content
        assert '| find "12345"' in content
        assert "tasklist" in content

    def test_moves_staged_to_exe(self, tmp_path):
        exe = _fake_exe(tmp_path, "MeterApp.exe")
        staged = tmp_path / "MeterApp.exe.new"
        log = tmp_path / "MeterApp.exe.update.log"
        content = mod.swap_bat_content(exe, staged, 1, log)
        assert 'move /y "' in content
        assert "MeterApp.exe.new" in content
        assert "MeterApp.exe" in content

    def test_success_marks_complete_and_deletes_staged(self, tmp_path):
        exe = _fake_exe(tmp_path)
        log = exe.with_name("app.exe.update.log")
        content = mod.swap_bat_content(exe, tmp_path / "app.exe.new", 1, log)
        assert "Update complete - you can now start the new version." in content
        assert 'del /q "C:' in content

    def test_failure_keeps_window_open_with_log(self, tmp_path):
        exe = _fake_exe(tmp_path)
        log = exe.with_name("app.exe.update.log")
        content = mod.swap_bat_content(exe, tmp_path / "app.exe.new", 1, log)
        assert "UPDATE FAILED" in content
        assert "your current version is still in place" in content
        assert str(log) in content
        assert "pause >nul" in content

    def test_no_five_second_close_and_detached_self_delete(self, tmp_path):
        exe = _fake_exe(tmp_path)
        log = exe.with_name("app.exe.update.log")
        content = mod.swap_bat_content(exe, tmp_path / "app.exe.new", 1, log)
        assert "waitfor /t 5" not in content
        # the batch must NOT delay the success-path close...
        assert "Update complete" in content
        # ...and self-deleting "%~f0" must run detached so cmd exits 0 cleanly
        assert 'start "" /b cmd /c "del /q ""%~f0""' in content

    def test_exact_crlf_no_double_cr(self, tmp_path):
        exe = _fake_exe(tmp_path)
        log = exe.with_name("app.exe.update.log")
        content = mod.swap_bat_content(exe, tmp_path / "app.exe.new", 1, log)
        raw = content.encode("utf-8")
        assert b"\r\r\n" not in raw, "strict CRLF - \\r\\r\\n breaks cmd/VBScript"
        body = raw.replace(b"\r\n", b"")
        assert b"\r" not in body and b"\n" not in body


class TestLauncherVbs:
    def test_exact_crlf_and_quoting(self, tmp_path):
        vbs = mod.build_launcher_vbs(tmp_path / "app_update.bat")
        raw = vbs.encode("utf-8")
        assert b"\r\r\n" not in raw
        assert 'CreateObject("WScript.Shell")' in vbs
        assert 'objShell.Run "cmd /c ""' in vbs  # VBS escaping of the quoted path
        assert ", 7, False" in vbs

    def test_launch_writes_vbs_and_calls_wscript(self, tmp_path):
        batch = tmp_path / "app_update.bat"
        batch.write_bytes(b"@echo off\r\n")
        with mock.patch("github_updater.windows_updater.subprocess.Popen") as popen:
            ok = mod.launch_helper(batch, "app")
        assert ok is True
        popen.assert_called_once()
        args = popen.call_args[0][0]
        assert args[0].lower() == "wscript.exe"
        vbs = Path(tempfile.gettempdir()) / "app_update.vbs"
        assert vbs.is_file()
        assert b"\r\r\n" not in vbs.read_bytes()
        vbs.unlink(missing_ok=True)

    def test_launch_failure_raises(self, tmp_path):
        batch = tmp_path / "app_update.bat"
        with mock.patch(
            "github_updater.windows_updater.subprocess.Popen",
            side_effect=OSError("boom"),
        ):
            with pytest.raises(UpdateError, match="Could not launch"):
                mod.launch_helper(batch, "app")
class TestApplyUpdate:
    def test_not_frozen_raises(self, tmp_path):
        with mock.patch.object(mod, "_current_exe", return_value=None):
            with pytest.raises(UpdateError, match="packaged"):
                mod.apply_update(str(_fake_download(tmp_path)))

    def test_missing_download_raises(self, tmp_path):
        exe = _fake_exe(tmp_path)
        with mock.patch.object(mod, "_current_exe", return_value=exe):
            with pytest.raises(UpdateError, match="not found"):
                mod.apply_update(str(tmp_path / "missing.exe"))

    def test_validation_failure_leaves_exe_and_no_stage(self, tmp_path):
        exe = _fake_exe(tmp_path)
        tiny = tmp_path / "tiny.exe"
        tiny.write_bytes(b"MZ")
        with mock.patch.object(mod, "_current_exe", return_value=exe):
            with pytest.raises(UpdateError, match="unexpectedly small"):
                mod.apply_update(str(tiny))
        assert exe.is_file()
        assert not (tmp_path / "GasmeterDownloader.exe.new").exists()

    def test_stages_new_and_launches_without_touching_exe(self, tmp_path):
        exe = _fake_exe(tmp_path)
        original = exe.read_bytes()
        download = _fake_download(tmp_path)
        with (
            mock.patch.object(mod, "_current_exe", return_value=exe),
            mock.patch.object(mod, "launch_helper", return_value=True) as launch,
        ):
            ok = mod.apply_update(str(download))
        assert ok is True
        launch.assert_called_once()
        staged = tmp_path / "GasmeterDownloader.exe.new"
        assert staged.is_file()
        assert exe.read_bytes() == original  # original never renamed/removed
        assert not (tmp_path / "GasmeterDownloader.exe.old").exists()
        assert staged.parent == exe.parent  # same volume

    def test_write_probe_failure_aborts_before_staging(self, tmp_path):
        exe = _fake_exe(tmp_path)
        download = _fake_download(tmp_path)
        with (
            mock.patch.object(mod, "_current_exe", return_value=exe),
            mock.patch.object(mod, "write_probe", side_effect=UpdateError("not writable")),
        ):
            with pytest.raises(UpdateError, match="not writable"):
                mod.apply_update(str(download))
        assert not (tmp_path / "GasmeterDownloader.exe.new").exists()

    def test_launch_failure_cleans_staged_and_raises(self, tmp_path):
        exe = _fake_exe(tmp_path)
        download = _fake_download(tmp_path)
        with (
            mock.patch.object(mod, "_current_exe", return_value=exe),
            mock.patch.object(mod, "launch_helper", return_value=False),
        ):
            with pytest.raises(UpdateError, match="Could not launch"):
                mod.apply_update(str(download))
        assert not (tmp_path / "GasmeterDownloader.exe.new").exists()
        assert exe.is_file()


class TestCleanOldFiles:
    def test_removes_old_new_and_log(self, tmp_path):
        exe = _fake_exe(tmp_path)  # GasmeterDownloader.exe
        (tmp_path / "GasmeterDownloader.exe.old").write_bytes(b"x")
        (tmp_path / "GasmeterDownloader.exe.new").write_bytes(b"y")
        (tmp_path / "GasmeterDownloader.exe.update.log").write_bytes(b"log")
        mod.clean_old_files(str(exe))
        assert not (tmp_path / "GasmeterDownloader.exe.old").exists()
        assert not (tmp_path / "GasmeterDownloader.exe.new").exists()
        assert not (tmp_path / "GasmeterDownloader.exe.update.log").exists()
        assert exe.is_file()

    def test_restores_when_exe_missing(self, tmp_path):
        exe = tmp_path / "app.exe"
        (tmp_path / "app.exe.old").write_bytes(b"MZ-old")
        mod.clean_old_files(str(exe))
        assert exe.is_file()
        assert exe.read_bytes() == b"MZ-old"

    def test_no_frozen_uses_current_exe(self, monkeypatch, tmp_path):
        exe = _fake_exe(tmp_path)  # GasmeterDownloader.exe
        (tmp_path / "GasmeterDownloader.exe.old").write_bytes(b"x")
        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr("sys.executable", str(exe))
        mod.clean_old_files()
        assert not (tmp_path / "GasmeterDownloader.exe.old").exists()

    def test_empty_path_no_error(self):
        mod.clean_old_files("")


@on_windows
class TestRealCmdSwap:
    def test_batch_replaces_exe_via_cmd(self, tmp_path):
        """The generated batch actually swaps staged .new over the exe via cmd."""
        exe = _fake_exe(tmp_path, "RealApp.exe")
        original = exe.read_bytes()
        staged = tmp_path / "RealApp.exe.new"
        staged.write_bytes(b"MZ" + b"NEWDATA" * 2000)
        log = tmp_path / "RealApp.exe.update.log"

        DEAD_PID = 999_999_999  # no such process -> wait loop exits immediately
        content = mod.swap_bat_content(exe, staged, DEAD_PID, log)
        batch = tmp_path / "swap_test.bat"
        batch.write_bytes(content.encode("utf-8"))

        proc = subprocess.run(
            ["cmd", "/c", str(batch)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, f"batch failed: {proc.stdout} {proc.stderr}"
        assert exe.read_bytes() != original
        assert exe.read_bytes()[:2] == b"MZ"
        assert not staged.exists()  # staged cleanup
        assert log.is_file()
        assert "Update complete" in log.read_text()

    def test_failure_leaves_original_intact(self, tmp_path, monkeypatch):
        """If the staged file is missing, the ORIGINAL exe stays in place."""
        # speed up the retry loop for the test (no 60 s wait)
        monkeypatch.setattr(mod, "MOVE_RETRIES", 2)
        monkeypatch.setattr(mod, "MOVE_RETRY_WAIT_SECONDS", 0)
        exe = _fake_exe(tmp_path, "KeepApp.exe")
        original = exe.read_bytes()
        staged = tmp_path / "KeepApp.exe.new"  # deliberately not created
        log = tmp_path / "KeepApp.exe.update.log"
        DEAD_PID = 999_999_999
        content = mod.swap_bat_content(exe, staged, DEAD_PID, log)
        batch = tmp_path / "keep_fail.bat"
        batch.write_bytes(content.encode("utf-8"))

        # The move retries then gives up; 'pause' would hang, so feed newline
        subprocess.run(
            ["cmd", "/c", str(batch)],
            input="\n",
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert exe.read_bytes() == original  # never renamed/removed
        assert log.is_file()
        assert "UPDATE FAILED" in log.read_text()
class TestApplyRecovery:
    def test_apply_restores_broken_old_state_first(self, tmp_path):
        """A leftover .old with no exe (v0.x crash) must be restored up front."""
        exe = tmp_path / "app.exe"  # not present yet
        (tmp_path / "app.exe.old").write_bytes(b"MZ-old-backup")
        download = _fake_download(tmp_path)
        with (
            mock.patch.object(mod, "_current_exe", return_value=exe),
            mock.patch.object(mod, "launch_helper", return_value=True),
        ):
            ok = mod.apply_update(str(download))
        assert ok is True
        assert exe.is_file()  # restored backup present again
        assert not (tmp_path / "app.exe.old").exists()
