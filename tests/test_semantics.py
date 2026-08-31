"""Tests for github_updater.semantics - pure version/sanitize helpers."""

from __future__ import annotations

from github_updater import semantics


class TestCompareVersions:
    def test_newer_major(self):
        assert semantics.compare_versions("2.0.0", "1.9.9") == 1

    def test_newer_minor(self):
        assert semantics.compare_versions("1.2.0", "1.1.9") == 1

    def test_newer_patch(self):
        assert semantics.compare_versions("1.0.1", "1.0.0") == 1

    def test_equal(self):
        assert semantics.compare_versions("1.0.0", "1.0.0") == 0

    def test_older(self):
        assert semantics.compare_versions("1.0.0", "2.0.0") == -1

    def test_two_part_vs_three_part_equal(self):
        assert semantics.compare_versions("1.0", "1.0.0") == 0

    def test_single_part(self):
        assert semantics.compare_versions("2", "1") == 1
        assert semantics.compare_versions("1", "1") == 0

    def test_large_patch(self):
        assert semantics.compare_versions("1.0.100", "1.0.99") == 1

    def test_invalid_returns_zero(self):
        assert semantics.compare_versions("abc", "1.0.0") == 0
        assert semantics.compare_versions("1.0.0", "xyz") == 0
        assert semantics.compare_versions("foo", "bar") == 0

    def test_empty_strings(self):
        assert semantics.compare_versions("", "1.0.0") == 0
        assert semantics.compare_versions("1.0.0", "") == 0


class TestIsNewer:
    def test_newer(self):
        assert semantics.is_newer("1.1.0", "1.0.9") is True

    def test_equal_false(self):
        assert semantics.is_newer("1.0.0", "1.0.0") is False

    def test_older_false(self):
        assert semantics.is_newer("1.0.0", "1.1.0") is False

    def test_invalid_false(self):
        assert semantics.is_newer("abc", "1.0.0") is False


class TestSanitizeAppName:
    def test_spaces_dots_and_bang_removed(self):
        assert semantics.sanitize_app_name("My Cool App!") == "mycoolapp"

    def test_movies_series_autosort(self):
        assert semantics.sanitize_app_name("Movies & Series Autosort") == "moviesseriesautosort"

    def test_keeps_digits(self):
        assert semantics.sanitize_app_name("App 2.0") == "app20"

    def test_lowercases(self):
        assert semantics.sanitize_app_name("  GASTEST ") == "gastest"
