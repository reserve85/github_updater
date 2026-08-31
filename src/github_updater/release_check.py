"""GitHub release check - network logic for ``UpdateService.check_for_update``.

Only the standard library is used; the result is a typed
:class:`~github_updater.models.UpdateCheckResult` so consumers never have to
guess at dict keys.
"""

from __future__ import annotations

import json
import logging
from urllib.error import URLError
from urllib.request import Request, urlopen

from github_updater.models import UpdateCheckResult
from github_updater.semantics import is_newer

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"


def check_for_update(
    current_version: str,
    owner: str,
    repo: str,
    app_name: str,
    token: str = "",
) -> UpdateCheckResult:
    """Check GitHub for a newer release.

    Works without a token on public repositories. Asset selection order:
    ``.exe`` first, then ``.zip``, then the zipball fallback. Network or
    parsing failures are reported in ``result.error`` (no exception).
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": app_name,
    }
    if token:
        if token.startswith("github_pat"):
            headers["Authorization"] = f"Bearer {token}"
        else:
            headers["Authorization"] = f"token {token}"

    url = GITHUB_API.format(owner=owner, repo=repo)
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())

        tag = data.get("tag_name", "")
        latest = tag.lstrip("v")
        release_notes = data.get("body", "")
        download_url = _select_asset_url(data)

        has_update = is_newer(latest, current_version)
        return UpdateCheckResult(
            has_update=has_update,
            latest_version=latest,
            download_url=download_url,
            release_notes=release_notes,
            error="",
        )
    except URLError as exc:
        return UpdateCheckResult(error=f"Network error: {exc.reason}")
    except Exception as exc:  # noqa: BLE001 - json/parsing robustness
        logger.exception("Update check failed")
        return UpdateCheckResult(error=str(exc))


def _select_asset_url(release_data: dict) -> str:
    """First matching asset URL: ``.exe`` -> ``.zip`` -> ``zipball_url``."""
    assets = release_data.get("assets", []) or []
    for asset in assets:
        if asset.get("name", "").endswith(".exe"):
            return asset.get("url", "")
    for asset in assets:
        if asset.get("name", "").endswith(".zip"):
            return asset.get("url", "")
    return release_data.get("zipball_url", "")
