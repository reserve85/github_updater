"""Tests for github_updater.update_service — GitHub update checker and downloader."""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from github_updater.update_service import UpdateService, GITHUB_API

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OWNER = "reserve85"
REPO = "TestApp"
APP_NAME = "TestApp"


def _svc(version: str = "1.0.0") -> UpdateService:
    """Create a standard UpdateService for tests."""
    return UpdateService(
        current_version=version, owner=OWNER, repo=REPO, app_name=APP_NAME,
    )


def _make_release_response(
    tag="v1.1.0",
    assets=None,
    zipball_url=f"https://api.github.com/repos/{OWNER}/{REPO}/zipball/v1.1.0",
    body="Release notes here",
):
    return {
        "tag_name": tag,
        "body": body,
        "assets": assets or [],
        "zipball_url": zipball_url,
    }


def _make_asset(name, url=None, browser_url=None):
    asset = {"name": name}
    if url:
        asset["url"] = url
    if browser_url:
        asset["browser_download_url"] = browser_url
    return asset


def _mock_urlopen(response_data):
    body = json.dumps(response_data).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ===========================================================================
# _is_newer
# ===========================================================================

class TestIsNewer:
    def test_newer_major(self):
        assert UpdateService._is_newer("2.0.0", "1.9.9") is True

    def test_newer_minor(self):
        assert UpdateService._is_newer("1.2.0", "1.1.9") is True

    def test_newer_patch(self):
        assert UpdateService._is_newer("1.0.1", "1.0.0") is True

    def test_equal_versions(self):
        assert UpdateService._is_newer("1.0.0", "1.0.0") is False

    def test_older_version(self):
        assert UpdateService._is_newer("1.0.0", "2.0.0") is False

    def test_two_part_vs_three_part_equal(self):
        assert UpdateService._is_newer("1.0", "1.0.0") is False

    def test_single_part_versions(self):
        assert UpdateService._is_newer("2", "1") is True
        assert UpdateService._is_newer("1", "1") is False

    def test_invalid_returns_false(self):
        assert UpdateService._is_newer("abc", "1.0.0") is False
        assert UpdateService._is_newer("1.0.0", "xyz") is False
        assert UpdateService._is_newer("foo", "bar") is False

    def test_empty_strings(self):
        assert UpdateService._is_newer("", "1.0.0") is False
        assert UpdateService._is_newer("1.0.0", "") is False
        assert UpdateService._is_newer("", "") is False

    def test_large_patch_number(self):
        assert UpdateService._is_newer("1.0.100", "1.0.99") is True


# ===========================================================================
# check_for_update
# ===========================================================================

class TestCheckForUpdate:
    @patch("github_updater.update_service.urlopen")
    def test_no_token_checks_public_repo(self, mock_urlopen):
        svc = _svc("1.0.0")
        mock_urlopen.return_value = _mock_urlopen(_make_release_response(tag="v1.1.0"))
        result = svc.check_for_update("")
        assert result["error"] == ""
        assert result["has_update"] is True
        assert result["latest_version"] == "1.1.0"

    @patch("github_updater.update_service.urlopen")
    def test_no_token_sends_no_authorization_header(self, mock_urlopen):
        svc = _svc("1.0.0")
        mock_urlopen.return_value = _mock_urlopen(_make_release_response(tag="v1.1.0"))
        svc.check_for_update("")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") is None
        assert req.get_header("Accept") == "application/vnd.github.v3+json"

    @patch("github_updater.update_service.urlopen")
    def test_no_update_available(self, mock_urlopen):
        svc = _svc("1.1.0")
        mock_urlopen.return_value = _mock_urlopen(_make_release_response(tag="v1.1.0"))
        result = svc.check_for_update("ghp_test")
        assert result["has_update"] is False
        assert result["latest_version"] == "1.1.0"

    @patch("github_updater.update_service.urlopen")
    def test_update_available_with_exe(self, mock_urlopen):
        svc = _svc("1.0.0")
        api_url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/assets/999"
        mock_urlopen.return_value = _mock_urlopen(
            _make_release_response(tag="v1.1.0", assets=[_make_asset("TestApp.exe", url=api_url)])
        )
        result = svc.check_for_update("ghp_test")
        assert result["has_update"] is True
        assert result["download_url"] == api_url
        assert result["release_notes"] == "Release notes here"

    @patch("github_updater.update_service.urlopen")
    def test_update_fallback_to_zip(self, mock_urlopen):
        svc = _svc("1.0.0")
        zip_url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/assets/888"
        mock_urlopen.return_value = _mock_urlopen(
            _make_release_response(tag="v1.1.0", assets=[_make_asset("source.zip", url=zip_url)])
        )
        result = svc.check_for_update("ghp_test")
        assert result["has_update"] is True
        assert result["download_url"] == zip_url

    @patch("github_updater.update_service.urlopen")
    def test_update_fallback_to_zipball(self, mock_urlopen):
        svc = _svc("1.0.0")
        mock_urlopen.return_value = _mock_urlopen(
            _make_release_response(tag="v1.1.0", assets=[])
        )
        result = svc.check_for_update("ghp_test")
        assert result["has_update"] is True
        assert "zipball" in result["download_url"]

    @patch("github_updater.update_service.urlopen")
    def test_network_error(self, mock_urlopen):
        from urllib.error import URLError
        svc = _svc()
        mock_urlopen.side_effect = URLError("Connection refused")
        result = svc.check_for_update("ghp_test")
        assert "Network error" in result["error"]

    @patch("github_updater.update_service.urlopen")
    def test_bearer_for_github_pat(self, mock_urlopen):
        svc = _svc("1.0.0")
        mock_urlopen.return_value = _mock_urlopen(_make_release_response(tag="v1.1.0"))
        svc.check_for_update("github_pat_test123")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer github_pat_test123"

    @patch("github_updater.update_service.urlopen")
    def test_token_for_classic(self, mock_urlopen):
        svc = _svc("1.0.0")
        mock_urlopen.return_value = _mock_urlopen(_make_release_response(tag="v1.1.0"))
        svc.check_for_update("ghp_test")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "token ghp_test"

    @patch("github_updater.update_service.urlopen")
    def test_user_agent_matches_app_name(self, mock_urlopen):
        svc = _svc("1.0.0")
        mock_urlopen.return_value = _mock_urlopen(_make_release_response(tag="v1.1.0"))
        svc.check_for_update("ghp_test")
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("User-agent") == "testapp"


# ===========================================================================
# download_update
# ===========================================================================

class TestDownloadUpdate:
    @patch("github_updater.update_service.urlopen")
    def test_download_exe_success(self, mock_urlopen):
        svc = _svc()
        fake_content = b"MZ fake exe content"
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [fake_content, b""]
        mock_resp.headers = {"Content-Length": str(len(fake_content))}
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/assets/999"
        result = svc.download_update(url, "ghp_test")
        assert result != ""
        assert result.endswith(".exe")
        assert os.path.exists(result)
        os.unlink(result)

    @patch("github_updater.update_service.urlopen")
    def test_download_zip_success(self, mock_urlopen):
        svc = _svc()
        fake_content = b"PK fake zip content"
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [fake_content, b""]
        mock_resp.headers = {"Content-Length": str(len(fake_content))}
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        url = "https://api.github.com/repos/test/test/releases/assets/888.zip"
        result = svc.download_update(url, "ghp_test")
        assert result != ""
        assert result.endswith(".zip")
        os.unlink(result)

    @patch("github_updater.update_service.urlopen")
    def test_download_progress_callback(self, mock_urlopen):
        svc = _svc()
        fake_content = b"MZ" + b"\x00" * 1000
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [fake_content, b""]
        mock_resp.headers = {"Content-Length": str(len(fake_content))}
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        progress_calls = []
        url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/assets/999"
        result = svc.download_update(
            url, "ghp_test", progress_callback=lambda d, t: progress_calls.append((d, t))
        )
        assert len(progress_calls) > 0
        assert progress_calls[-1][0] == len(fake_content)
        os.unlink(result)

    @patch("github_updater.update_service.urlopen")
    def test_download_invalid_exe_returns_empty(self, mock_urlopen):
        svc = _svc()
        fake_content = b"PK not an exe"
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [fake_content, b""]
        mock_resp.headers = {"Content-Length": str(len(fake_content))}
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/assets/999"
        result = svc.download_update(url, "ghp_test")
        assert result == ""

    @patch("github_updater.update_service.urlopen")
    def test_download_anonymous_sends_octet_stream(self, mock_urlopen):
        svc = _svc()
        fake_content = b"MZ" + b"\x00" * 200
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [fake_content, b""]
        mock_resp.headers = {"Content-Length": str(len(fake_content))}
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/assets/999"
        result = svc.download_update(url, "")
        assert result != ""
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") is None
        assert req.get_header("Accept") == "application/octet-stream"
        os.unlink(result)


# ===========================================================================
# apply_update
# ===========================================================================

class TestApplyUpdate:
    def test_nonexistent_file_returns_false(self):
        svc = _svc()
        assert svc.apply_update("C:\\nonexistent\\file.exe") is False

    def test_not_frozen_returns_false(self, tmp_path):
        svc = _svc()
        fake = tmp_path / "test.exe"
        fake.write_bytes(b"MZ" + b"\x00" * 100)
        assert svc.apply_update(str(fake)) is False

    def test_invalid_exe_header_returns_false(self, tmp_path, monkeypatch):
        svc = _svc()
        fake = tmp_path / "test.exe"
        fake.write_bytes(b"PK" + b"\x00" * 100)
        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr("sys.executable", str(tmp_path / "app.exe"))
        assert svc.apply_update(str(fake)) is False

    def test_frozen_writes_bat_and_launches(self, tmp_path, monkeypatch):
        svc = _svc()
        new_exe = tmp_path / "update.exe"
        new_exe.write_bytes(b"MZ" + b"\x00" * 100)
        exe_path = tmp_path / "app.exe"
        exe_path.write_bytes(b"MZ" + b"\x00" * 50)

        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr("sys.executable", str(exe_path))
        launched = []
        monkeypatch.setattr(
            "github_updater.update_service.subprocess.Popen",
            lambda *a, **kw: launched.append(a),
        )

        result = svc.apply_update(str(new_exe))
        assert result is True
        assert len(launched) == 1

        import tempfile as _tf
        bat_path = os.path.join(_tf.gettempdir(), "testapp_update.bat")
        assert os.path.exists(bat_path)
        with open(bat_path) as f:
            content = f.read()
        assert str(exe_path) in content
        assert str(new_exe) in content
        assert "waitfor" in content
        assert "trycopy" in content

    def test_bat_has_no_auto_restart(self, tmp_path, monkeypatch):
        svc = _svc()
        new_exe = tmp_path / "update.exe"
        new_exe.write_bytes(b"MZ" + b"\x00" * 100)
        exe_path = tmp_path / "app.exe"
        exe_path.write_bytes(b"MZ" + b"\x00" * 50)

        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr("sys.executable", str(exe_path))
        monkeypatch.setattr(
            "github_updater.update_service.subprocess.Popen", lambda *a, **kw: None,
        )

        svc.apply_update(str(new_exe))
        import tempfile as _tf
        bat_path = os.path.join(_tf.gettempdir(), "testapp_update.bat")
        with open(bat_path) as f:
            content = f.read()
        assert 'start ""' not in content

    def test_bat_script_waits_for_pid(self, tmp_path, monkeypatch):
        svc = _svc()
        new_exe = tmp_path / "update.exe"
        new_exe.write_bytes(b"MZ" + b"\x00" * 100)
        exe_path = tmp_path / "app.exe"
        exe_path.write_bytes(b"MZ" + b"\x00" * 50)

        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr("sys.executable", str(exe_path))
        monkeypatch.setattr(
            "github_updater.update_service.subprocess.Popen", lambda *a, **kw: None,
        )

        svc.apply_update(str(new_exe))
        import tempfile as _tf
        bat_path = os.path.join(_tf.gettempdir(), "testapp_update.bat")
        with open(bat_path) as f:
            content = f.read()
        assert f"PID eq {os.getpid()}" in content

    def test_bat_uses_app_name_in_filename(self, tmp_path, monkeypatch):
        svc = _svc()
        new_exe = tmp_path / "update.exe"
        new_exe.write_bytes(b"MZ" + b"\x00" * 100)
        exe_path = tmp_path / "app.exe"
        exe_path.write_bytes(b"MZ" + b"\x00" * 50)

        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr("sys.executable", str(exe_path))
        monkeypatch.setattr(
            "github_updater.update_service.subprocess.Popen", lambda *a, **kw: None,
        )

        svc.apply_update(str(new_exe))
        import tempfile as _tf
        assert os.path.exists(os.path.join(_tf.gettempdir(), "testapp_update.bat"))
        assert os.path.exists(os.path.join(_tf.gettempdir(), "testapp_update.vbs"))


# ===========================================================================
# clean_old_files / restart_app / constructor / GITHUB_API / flow
# ===========================================================================

class TestCleanOldFiles:
    def test_removes_old_file(self, tmp_path):
        exe = tmp_path / "app.exe"
        exe.write_bytes(b"MZ")
        old = tmp_path / "app.exe.old"
        old.write_bytes(b"MZ")
        UpdateService.clean_old_files(str(exe))
        assert not old.exists()

    def test_no_old_file_no_error(self, tmp_path):
        exe = tmp_path / "app.exe"
        exe.write_bytes(b"MZ")
        UpdateService.clean_old_files(str(exe))

    def test_empty_path_no_error(self):
        UpdateService.clean_old_files("")

    def test_none_path_uses_sys_executable(self, monkeypatch):
        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr("sys.executable", "C:\\fake\\app.exe")
        UpdateService.clean_old_files(None)


class TestRestartApp:
    def test_calls_os_exit(self, monkeypatch):
        svc = _svc()
        exit_calls = []
        monkeypatch.setattr(os, "_exit", lambda code: exit_calls.append(code))
        svc.restart_app()
        assert exit_calls == [0]


class TestGitHubApiConstant:
    def test_url_contains_placeholders(self):
        assert "{owner}" in GITHUB_API
        assert "{repo}" in GITHUB_API

    def test_url_format(self):
        url = GITHUB_API.format(owner="octocat", repo="hello-world")
        assert url == "https://api.github.com/repos/octocat/hello-world/releases/latest"


class TestConstructor:
    def test_app_name_sanitized(self):
        svc = UpdateService("1.0.0", "owner", "repo", "My Cool App!")
        assert svc._app_name == "mycoolapp"

    def test_app_name_with_spaces_and_dots(self):
        svc = UpdateService("1.0.0", "owner", "repo", "Movies & Series Autosort")
        assert svc._app_name == "moviesseriesautosort"

    def test_current_version_stored(self):
        svc = UpdateService("2.5.1", "owner", "repo", "App")
        assert svc.current_version == "2.5.1"

    def test_owner_repo_stored(self):
        svc = UpdateService("1.0.0", "myowner", "myrepo", "App")
        assert svc.owner == "myowner"
        assert svc.repo == "myrepo"


class TestUpdateFlow:
    @patch("github_updater.update_service.urlopen")
    def test_full_flow_check_then_download(self, mock_urlopen):
        svc = _svc("1.0.0")
        api_url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/assets/999"
        assets = [_make_asset("TestApp.exe", url=api_url)]
        mock_urlopen.return_value = _mock_urlopen(
            _make_release_response(tag="v1.1.0", assets=assets)
        )
        check_result = svc.check_for_update("ghp_test")
        assert check_result["has_update"] is True

        fake_content = b"MZ fake exe"
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [fake_content, b""]
        mock_resp.headers = {"Content-Length": str(len(fake_content))}
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        download_path = svc.download_update(check_result["download_url"], "ghp_test")
        assert download_path != ""
        assert download_path.endswith(".exe")
        assert os.path.exists(download_path)
        os.unlink(download_path)

    @patch("github_updater.update_service.urlopen")
    def test_full_flow_no_update(self, mock_urlopen):
        svc = _svc("1.0.0")
        mock_urlopen.return_value = _mock_urlopen(_make_release_response(tag="v1.0.0"))
        result = svc.check_for_update("ghp_test")
        assert result["has_update"] is False
        assert result["download_url"] == ""
