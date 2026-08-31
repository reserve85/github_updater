"""Typed results and the shared error type for github_updater.

All public entry points return one of these dataclasses; failures that can be
explained to the user raise :class:`UpdateError` instead of hidden falsy values.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    """Outcome of a GitHub release check."""

    has_update: bool = False
    latest_version: str = ""
    download_url: str = ""
    release_notes: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, str | bool]:
        """Back-compat bridge: the exact dict shape returned by v1.x."""
        return {
            "has_update": self.has_update,
            "latest_version": self.latest_version,
            "download_url": self.download_url,
            "release_notes": self.release_notes,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Outcome of an asset download."""

    path: str = ""  # temp path of the validated download; "" on failure
    error: str = ""


class UpdateError(Exception):
    """A user-presentable updater failure (safe apply / check / download)."""
