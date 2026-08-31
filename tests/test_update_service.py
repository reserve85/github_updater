"""Facade-level tests for github_updater.UpdateService.

These verify the public API contract (constructor, typed results, delegation to
the focused modules, and the back-compat ``as_dict`` bridge). The per-module
network/batch details live in the sibling test files.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from github_updater.models import DownloadResult, UpdateCheckResult, UpdateError
from github_updater.update_service import GITHUB_API, UpdateService

OWNER = "reserve85"
REPO = "TestApp"
APP_NAME = "TestApp"


def _svc(version: str = "1.0.0") -> UpdateService:
    return UpdateService(
        current_version=version, owner=OWNER, repo=REPO, app_name=APP_NAME
    )


# ===========================================================================
# Constructor
# ===========================================================================

class TestConstructor:
    def test_app_name_sanitized(self):
        svc = UpdateService("1.0.0", "owner", "repo", "My Cool App!")
        assert svc._app_name == "mycoolapp"  # noqa: SLF001

    def test_app_name_with_spaces_and_dots(self):
        svc = UpdateService("1.0.0", "owner", "repo", "Movies & Series Autosort")
        assert svc._app_name == "moviesseriesautosort"  # noqa: SLF001

    def test_current_version_stored(self):
        svc = UpdateService("2.5.1", "owner", "repo", "App")
        assert svc.current_version == "2.5.1"

    def test_owner_repo_stored(self):
        svc = UpdateService("1.0.0", "myowner", "myrepo", "App")
        assert svc.owner == "myowner"
        assert svc.repo == "myrepo"


# ===========================================================================
# check_for_update
# ===========================================================================

class TestCheckForUpdate:
    @mock.patch("github_updater.update_service._check")
    def test_delegates_and_returns_typed_result(self, check):
        check.return_value = UpdateCheckResult(has_update=True, latest_version="2.0.0")
        result = _svc().check_for_update("ghp_x")
        assert isinstance(result, UpdateCheckResult)
        assert result.has_update is True
        check.assert_called_once()
        kwargs = check.call_args.kwargs
        assert kwargs["current_version"] == "1.0.0"
        assert kwargs["owner"] == OWNER
        assert kwargs["repo"] == REPO
        assert kwargs["token"] == "ghp_x"

    @mock.patch("github_updater.update_service._check")
    def test_empty_token_passed_as_empty(self, check):
        _svc().check_for_update("")
        assert check.call_args.kwargs["token"] == ""

    @mock.patch("github_updater.update_service._check")
    def test_as_dict_bridge_is_v1x_shape(self, check):
        check.return_value = UpdateCheckResult(
            has_update=True, latest_version="2.0.0", download_url="u"
        )
        d = _svc().check_for_update("").as_dict()
        assert d == {
            "has_update": True,
            "latest_version": "2.0.0",
            "download_url": "u",
            "release_notes": "",
            "error": "",
        }
# ===========================================================================
# download_update
# ===========================================================================

class TestDownloadUpdate:
    @mock.patch("github_updater.update_service._download")
    def test_delegates_and_returns_typed_result(self, download):
        download.return_value = DownloadResult(path="C:\\tmp\\a.exe")
        result = _svc().download_update("http://x", "")
        assert isinstance(result, DownloadResult)
        assert result.path == "C:\\tmp\\a.exe"
        assert download.call_args.args[0] == "http://x"

    @mock.patch("github_updater.update_service._download")
    def test_progress_callback_forwarded(self, download):
        def noop(*_):
            return None

        _svc().download_update("http://x", "", noop)
        assert download.call_args.kwargs["progress_callback"] is noop


# ===========================================================================
# apply_update / restart / clean_old_files
# ===========================================================================

class TestApplyUpdate:
    @mock.patch("github_updater.update_service._apply", return_value=True)
    def test_delegates(self, apply):
        assert _svc().apply_update("/tmp/a.exe") is True
        apply.assert_called_once_with("/tmp/a.exe")

    @mock.patch(
        "github_updater.update_service._apply",
        side_effect=UpdateError("not writable"),
    )
    def test_update_error_propagates(self, apply):
        with pytest.raises(UpdateError, match="not writable"):
            _svc().apply_update("/tmp/a.exe")


class TestRestartApp:
    def test_calls_os_exit(self, monkeypatch):
        calls = []
        monkeypatch.setattr(os, "_exit", lambda code: calls.append(code))
        _svc().restart_app()
        assert calls == [0]


class TestCleanOldFiles:
    @mock.patch("github_updater.update_service._clean_old_files")
    def test_delegates(self, clean):
        UpdateService.clean_old_files("C:\\x\\app.exe")
        clean.assert_called_once_with("C:\\x\\app.exe")

    @mock.patch("github_updater.update_service._clean_old_files")
    def test_no_arg_delegates_none(self, clean):
        UpdateService.clean_old_files()
        clean.assert_called_once_with(None)


# ===========================================================================
# _is_newer back-compat helper
# ===========================================================================

class TestIsNewer:
    def test_true(self):
        assert UpdateService._is_newer("2.0.0", "1.9.9") is True

    def test_false_equal(self):
        assert UpdateService._is_newer("1.0.0", "1.0.0") is False

    def test_false_older(self):
        assert UpdateService._is_newer("1.0.0", "2.0.0") is False


# ===========================================================================
# GITHUB_API constant
# ===========================================================================

class TestGitHubApiConstant:
    def test_url_contains_placeholders(self):
        assert "{owner}" in GITHUB_API
        assert "{repo}" in GITHUB_API

    def test_url_format(self):
        url = GITHUB_API.format(owner="octocat", repo="hello-world")
        assert url == "https://api.github.com/repos/octocat/hello-world/releases/latest"
