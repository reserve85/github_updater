"""Tests for github_updater.release_check - the GitHub latest-release lookup."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from github_updater import release_check

OWNER = "reserve85"
REPO = "TestApp"
APP_NAME = "TestApp"


def _make_release(
    tag="v1.1.0",
    assets=None,
    zipball="https://api.github.com/repos/x/zipball/v1.1.0",
    body="Release notes",
):
    return {"tag_name": tag, "body": body, "assets": assets or [], "zipball_url": zipball}


def _make_asset(name, url):
    return {"name": name, "url": url}


def _mock_urlopen(release_data):
    body = json.dumps(release_data).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _check(version="1.0.0", token="", release=None, side_effect=None):
    with patch("github_updater.release_check.urlopen") as m:
        m.side_effect = side_effect
        if release is not None:
            m.return_value = _mock_urlopen(release)
        return release_check.check_for_update(
            current_version=version, owner=OWNER, repo=REPO, app_name=APP_NAME, token=token
        ), m


class TestCheckForUpdate:
    def test_no_token_checks_public_repo(self):
        result, mock_urlopen = _check(release=_make_release(tag="v1.1.0"))
        assert result.has_update is True
        assert result.latest_version == "1.1.0"
        assert result.release_notes == "Release notes"
        assert result.error == ""

    def test_no_token_sends_no_authorization_header(self):
        _, mock_urlopen = _check(token="", release=_make_release(tag="v1.1.0"))
        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") is None
        assert req.get_header("Accept") == "application/vnd.github.v3+json"

    def test_no_update_available(self):
        result, _ = _check(version="1.1.0", release=_make_release(tag="v1.1.0"))
        assert result.has_update is False
        assert result.latest_version == "1.1.0"

    def test_update_available_with_exe(self):
        api_url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/assets/999"
        result, _ = _check(
            release=_make_release(
                tag="v1.1.0", assets=[_make_asset("TestApp.exe", api_url)]
            )
        )
        assert result.has_update is True
        assert result.download_url == api_url
        assert result.release_notes == "Release notes"

    def test_exe_preferred_over_zip(self):
        exe_url = "https://api.github.com/repos/x/assets/exe"
        zip_url = "https://api.github.com/repos/x/assets/zip"
        release = _make_release(
            assets=[_make_asset("src.zip", zip_url), _make_asset("TestApp.exe", exe_url)]
        )
        result, _ = _check(release=release)
        assert result.download_url == exe_url

    def test_update_fallback_to_zip(self):
        zip_url = "https://api.github.com/repos/x/assets/888"
        result, _ = _check(
            release=_make_release(
                tag="v1.1.0", assets=[_make_asset("source.zip", zip_url)]
            )
        )
        assert result.has_update is True
        assert result.download_url == zip_url

    def test_update_fallback_to_zipball(self):
        result, _ = _check(release=_make_release(tag="v1.1.0", assets=[]))
        assert result.has_update is True
        assert "zipball" in result.download_url

    def test_network_error(self):
        from urllib.error import URLError
        result, _ = _check(side_effect=URLError("Connection refused"))
        assert result.error == "Network error: Connection refused"
        assert result.has_update is False

    def test_bearer_for_github_pat(self):
        release = _make_release(tag="v1.1.0")
        with patch("github_updater.release_check.urlopen") as m:
            m.return_value = _mock_urlopen(release)
            release_check.check_for_update(
                "1.0.0", OWNER, REPO, APP_NAME, token="github_pat_test123"
            )
            req = m.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer github_pat_test123"

    def test_classic_token_uses_token_scheme(self):
        release = _make_release(tag="v1.1.0")
        with patch("github_updater.release_check.urlopen") as m:
            m.return_value = _mock_urlopen(release)
            release_check.check_for_update("1.0.0", OWNER, REPO, APP_NAME, token="ghp_abc")
            req = m.call_args[0][0]
        assert req.get_header("Authorization") == "token ghp_abc"

    def test_user_agent_uses_sanitized_app_name(self):
        release = _make_release(tag="v1.1.0")
        with patch("github_updater.release_check.urlopen") as m:
            m.return_value = _mock_urlopen(release)
            release_check.check_for_update("1.0.0", OWNER, REPO, "Test App")
            req = m.call_args[0][0]
        # urllib.Request stores headers with the key as-dict-normalized ("User-agent")
        assert req.get_header("User-agent") == "Test App"

    def test_no_tag_name(self):
        result, _ = _check(release={"tag_name": "", "body": "", "assets": [], "zipball_url": ""})
        assert result.latest_version == ""
        assert result.has_update is False


class TestSelectAssetUrl:
    def test_exe_wins(self):
        assert release_check._select_asset_url(
            {"assets": [{"name": "a.zip", "url": "z"}, {"name": "a.exe", "url": "e"}]}
        ) == "e"

    def test_zip_fallback(self):
        assert release_check._select_asset_url(
            {"assets": [{"name": "a.zip", "url": "z"}]}
        ) == "z"

    def test_zipball_fallback(self):
        assert release_check._select_asset_url({"assets": [], "zipball_url": "zb"}) == "zb"

    def test_empty(self):
        assert release_check._select_asset_url({}) == ""


class TestGitHubApiConstant:
    def test_formats_url(self):
        url = release_check.GITHUB_API.format(owner="octocat", repo="hello")
        assert url == "https://api.github.com/repos/octocat/hello/releases/latest"
