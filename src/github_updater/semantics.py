"""Pure, dependency-free helpers for github_updater."""

from __future__ import annotations

import re


def compare_versions(latest: str, current: str) -> int:
    """Semantic-compare dotted version strings.

    Returns -1, 0 or 1. Missing components are treated as 0 (``1.0 == 1.0.0``);
    any non-numeric component makes the comparison harmless (returns 0) so the
    caller never sees a spurious "update available".
    """
    try:
        latest_parts = [int(x) for x in latest.split(".")]
        current_parts = [int(x) for x in current.split(".")]
    except (ValueError, AttributeError):
        return 0
    width = max(len(latest_parts), len(current_parts))
    latest_parts += [0] * (width - len(latest_parts))
    current_parts += [0] * (width - len(current_parts))
    if latest_parts == current_parts:
        return 0
    return 1 if latest_parts > current_parts else -1


def is_newer(latest: str, current: str) -> bool:
    """True when ``latest`` is strictly newer than ``current``."""
    return compare_versions(latest, current) > 0


def sanitize_app_name(name: str) -> str:
    """Lower-case alphanumerics only; safe for file/temp names."""
    return re.sub(r"[^a-zA-Z0-9]", "", name).lower()
