"""Tests for github_updater.models - typed results and error."""

from __future__ import annotations

from github_updater.models import DownloadResult, UpdateCheckResult, UpdateError


class TestUpdateCheckResult:
    def test_defaults(self):
        r = UpdateCheckResult()
        assert r.has_update is False
        assert r.latest_version == ""
        assert r.download_url == ""
        assert r.release_notes == ""
        assert r.error == ""

    def test_fields_stored(self):
        r = UpdateCheckResult(
            has_update=True,
            latest_version="2.0.0",
            download_url="http://x/a.exe",
            release_notes="notes",
            error="",
        )
        assert r.has_update is True
        assert r.latest_version == "2.0.0"

    def test_as_dict_matches_v1x_shape(self):
        r = UpdateCheckResult(has_update=True, latest_version="2.0.0", download_url="u")
        d = r.as_dict()
        assert d == {
            "has_update": True,
            "latest_version": "2.0.0",
            "download_url": "u",
            "release_notes": "",
            "error": "",
        }

    def test_as_dict_keys_are_exact_v1x(self):
        assert set(UpdateCheckResult().as_dict()) == {
            "has_update",
            "latest_version",
            "download_url",
            "release_notes",
            "error",
        }


class TestDownloadResult:
    def test_defaults(self):
        d = DownloadResult()
        assert d.path == ""
        assert d.error == ""

    def test_failure(self):
        d = DownloadResult(error="boom")
        assert d.path == ""
        assert d.error == "boom"

    def test_success(self):
        d = DownloadResult(path="C:\\tmp\\a.exe")
        assert d.path == "C:\\tmp\\a.exe"
        assert d.error == ""


class TestUpdateError:
    def test_is_exception(self):
        assert issubclass(UpdateError, Exception)

    def test_message(self):
        e = UpdateError("small file")
        assert str(e) == "small file"
