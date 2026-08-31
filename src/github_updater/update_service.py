"""Public facade for github_updater.

Delegates to the focused modules underneath:

* ``github_updater.semantics`` - version comparison + app-name sanitizing
* ``github_updater.release_check`` - GitHub latest-release lookup
* ``github_updater.downloader`` - asset download + validation
* ``github_updater.windows_updater`` - the SAFE Windows EXE replacement

The public API (``check_for_update`` / ``download_update`` / ``apply_update`` /
``restart_app`` / ``clean_old_files`` / ``_is_newer``) is preserved; the
imperative ``apply_update`` now raises :class:`~github_updater.models.UpdateError`
on any preventable failure instead of silently returning ``False``.
"""

from __future__ import annotations

import os

from github_updater.downloader import download_update as _download
from github_updater.models import DownloadResult, UpdateCheckResult
from github_updater.release_check import GITHUB_API
from github_updater.release_check import check_for_update as _check
from github_updater.semantics import is_newer, sanitize_app_name
from github_updater.windows_updater import (
    apply_update as _apply,
)
from github_updater.windows_updater import (
    clean_old_files as _clean_old_files,
)

__all__ = ["UpdateService", "GITHUB_API"]


class UpdateService:
    """Check for updates and download/apply new versions from GitHub."""

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
        self._app_name = sanitize_app_name(app_name)

    # ------------------------------------------------------------------
    # Check / download
    # ------------------------------------------------------------------

    def check_for_update(self, token: str = "") -> UpdateCheckResult:
        """Check GitHub for a newer release (typed result)."""
        return _check(
            current_version=self.current_version,
            owner=self.owner,
            repo=self.repo,
            app_name=self._app_name,
            token=token or "",
        )

    def download_update(
        self,
        download_url: str,
        token: str = "",
        progress_callback=None,
    ) -> DownloadResult:
        """Download the update asset to a validated temp file (typed result)."""
        return _download(
            download_url,
            token or "",
            self._app_name,
            progress_callback=progress_callback,
        )

    # ------------------------------------------------------------------
    # Apply / restart / cleanup
    # ------------------------------------------------------------------

    def apply_update(self, path: str) -> bool:
        """Validate, stage and launch a SAFE self-replacement.

        Returns ``True`` only once the detached helper is running. Raises
        :class:`UpdateError` on any preventable failure.
        """
        return _apply(path)

    def restart_app(self) -> None:
        """Exit the app; the detached helper will swap in the new version."""
        os._exit(0)

    @staticmethod
    def clean_old_files(exe_path: str | None = None) -> None:
        """Restore a broken v0.x state, then remove leftover stages."""
        _clean_old_files(exe_path)

    # ------------------------------------------------------------------
    # Pure helpers (kept for back-compat)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_newer(latest: str, current: str) -> bool:
        return is_newer(latest, current)
