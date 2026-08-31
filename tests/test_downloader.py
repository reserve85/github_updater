"""Tests for github_updater.downloader - asset download + exe validation."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from github_updater import downloader

APP_NAME = "testapp"


def _make_resp(content: bytes, content_length: int | None = None):
    resp = MagicMock()
    resp.headers = {}
    total = content_length if content_length is not None else len(content)
    resp.headers["Content-Length"] = str(total)
    resp.read.side_effect = [content, b""]
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _fake_mkstemp(path: str):
    """Return a REAL (fd, path) pair so the code's ``os.close(fd)`` works."""

    def _mkstemp(suffix=""):
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
        return fd, path

    return _mkstemp


class TestDownloadUpdate:
    def test_download_exe_success(self, tmp_path, monkeypatch):
        target = str(tmp_path / "dl.exe")
        monkeypatch.setattr(downloader.tempfile, "mkstemp", _fake_mkstemp(target))
        with patch("github_updater.downloader.urlopen") as m:
            m.return_value = _make_resp(b"MZ fake exe")
            result = downloader.download_update("http://x/TestApp.exe", "", APP_NAME)
        assert result.error == ""
        assert result.path.endswith(".exe")
        assert os.path.exists(result.path)
        assert os.path.getsize(result.path) == len(b"MZ fake exe")

    def test_download_zip_success(self, tmp_path, monkeypatch):
        target = str(tmp_path / "dl.zip")
        monkeypatch.setattr(downloader.tempfile, "mkstemp", _fake_mkstemp(target))
        with patch("github_updater.downloader.urlopen") as m:
            m.return_value = _make_resp(b"PK fake zip")
            result = downloader.download_update("http://x/src.zip", "", APP_NAME)
        assert result.error == ""
        assert result.path.endswith(".zip")

    def test_invalid_exe_removed_and_errors(self, tmp_path, monkeypatch):
        target = str(tmp_path / "dl.exe")
        monkeypatch.setattr(downloader.tempfile, "mkstemp", _fake_mkstemp(target))
        with patch("github_updater.downloader.urlopen") as m:
            m.return_value = _make_resp(b"NOTMZ-not-an-exe")
            result = downloader.download_update("http://x/TestApp.exe", "", APP_NAME)
        assert result.path == ""
        assert "not a valid executable" in result.error
        assert not os.path.exists(target)

    def test_progress_callback_reports(self, tmp_path, monkeypatch):
        target = str(tmp_path / "dl.exe")
        monkeypatch.setattr(downloader.tempfile, "mkstemp", _fake_mkstemp(target))
        calls = []
        with patch("github_updater.downloader.urlopen") as m:
            m.return_value = _make_resp(b"MZfake", content_length=6)
            downloader.download_update(
                "http://x/TestApp.exe",
                "",
                APP_NAME,
                progress_callback=lambda done, total: calls.append((done, total)),
            )
        assert calls and calls[-1] == (6, 6)

    def test_network_failure_returns_error(self):
        from urllib.error import URLError

        with patch(
            "github_updater.downloader.urlopen", side_effect=URLError("down")
        ):
            result = downloader.download_update("http://x/TestApp.exe", "", APP_NAME)
        assert result.path == ""
        assert "down" in result.error

    def test_anonymous_sends_octet_stream(self, tmp_path, monkeypatch):
        target = str(tmp_path / "dl.exe")
        monkeypatch.setattr(downloader.tempfile, "mkstemp", _fake_mkstemp(target))
        with patch("github_updater.downloader.urlopen") as m:
            m.return_value = _make_resp(b"MZfake")
            downloader.download_update("http://x/TestApp.exe", "", APP_NAME)
            req = m.call_args[0][0]
        assert req.get_header("Accept") == "application/octet-stream"
        assert req.get_header("Authorization") is None

    def test_bearer_header_for_pat(self, tmp_path, monkeypatch):
        target = str(tmp_path / "dl.exe")
        monkeypatch.setattr(downloader.tempfile, "mkstemp", _fake_mkstemp(target))
        with patch("github_updater.downloader.urlopen") as m:
            m.return_value = _make_resp(b"MZfake")
            downloader.download_update("http://x/TestApp.exe", "github_pat_xyz", APP_NAME)
            req = m.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer github_pat_xyz"
