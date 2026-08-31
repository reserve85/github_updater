# Changelog

## v1.2.0 (2026-08-31)

### Safety (the reason for this release)

The previous `apply_update` renamed the running exe to `<exe>.old` **before** the
new file was in place and hid every batch error behind `>nul 2>&1`. If the copy
failed, the machine was left with only `.old` and no executable. v1.2.0 replaces
that with a stage-first, atomic-swap design:

- the downloaded file is validated (size + `MZ` header) **before** anything is touched,
- a leftover `v0.x` broken state (only `<exe>.old`, no exe) is restored automatically,
- the app folder is probed for write access and the new exe is staged as `<exe>.new`
  on the same volume,
- a detached helper waits for the process to exit, then retries the atomic `move`
  until the file lock clears; the original exe is never removed before the new one
  is in place,
- every step is logged to `<exe>.update.log`; failure keeps the window open with a
  readable message,
- the generated `.bat` is written with exact CRLF bytes (the text-mode `\r\r\n`
  broke the launcher) and is spawned hidden & detached via `cmd /c` - no
  VBScript/`wscript.exe` involved,
- startup `clean_old_files()` now restores a broken state before removing leftovers.

### API

- `check_for_update()` now returns a typed `UpdateCheckResult` (with `.as_dict()`
  matching the v1.x dict shape for back-compat).
- `download_update()` returns a typed `DownloadResult`.
- New `UpdateError` exception is raised on any preventable apply failure, instead of
  a silent `False`.

### Internals / maintainability

- Architecture split into focused modules: `semantics`, `release_check`, `downloader`,
  `windows_updater`, with `UpdateService` as a thin facade.
- Still **stdlib-only** (no runtime dependencies).
- Test suite expanded from 46 to **101 tests**, including a real `cmd /c` swap test
  and a batch-failure test that proves the original exe stays intact.
- Added GitHub Actions CI (Ubuntu + Windows, Python 3.11 + 3.12, ruff + pytest).

## v1.1.1 (2026-08-31)

- Update helper window closes immediately on success, stays open and states the
  error on failure.

## v1.1.0 (2026-08-31)

- Repository renamed from `Python_Units` to `github_updater`; URLs updated.
- Anonymous public-repo checks and downloads supported (no token required).

## v1.0.0 (2026-08-19)

- Initial shared `github_updater` package for cross-project auto-update support.