# github-updater

Shared GitHub release updater for Python desktop applications (**Windows EXE
self-replace**).

> **2026-08:** The repository was renamed from `Python_Units` to `github_updater`;
> the old URL redirects, so existing installs keep working.

Used by **Gasmeter-Downloader** (and available to other desktop apps).

## Why the safe swap matters

The pre-1.2.0 updater renamed the running exe to `<exe>.old` **before** the new
file was in place, hid batch errors behind `>nul 2>&1`, and could leave a machine
with only `.old` and no executable. v1.2.0 fixes that:

1. **validate** the download (size + `MZ` header) before touching anything,
2. **restore** a broken `v0.x` state (`.old` present, exe missing) automatically,
3. **probe** the app folder for write access, then **stage** the new exe as
   `<exe>.new` on the same volume,
4. a detached helper **waits** for the process to exit, then retries the atomic
   `move` until the file lock clears - the original exe is *never* removed before
   the new one is in place; the helper is a `.bat` written with exact CRLF bytes
   and spawned hidden & detached via `cmd /c` (no VBScript/`wscript.exe`),
5. every step is logged to `<exe>.update.log`; failures keep the window open with
   a readable message.

## Installation

```bash
pip install git+https://github.com/reserve85/github_updater.git
```

Or pin to a tag:

```bash
pip install git+https://github.com/reserve85/github_updater.git@v1.2.0
```

## Usage

```python
from github_updater import UpdateService, UpdateError

svc = UpdateService(
    current_version="1.2.0",
    owner="reserve85",
    repo="MyApp",
    app_name="MyApp",
)

result = svc.check_for_update(token="")       # -> UpdateCheckResult
if result.has_update:
    download = svc.download_update(
        result.download_url, token="", progress_callback=print
    )                                          # -> DownloadResult
    if download.path:
        try:
            svc.apply_update(download.path)    # -> True, or raises UpdateError
        except UpdateError as exc:
            print(f"Update failed: {exc}")     # current version still intact
            raise
        svc.restart_app()                      # exits the app
```

## API

### `UpdateService(current_version, owner, repo, app_name)`

| Parameter | Type | Description |
|---|---|---|
| `current_version` | `str` | Current app version (e.g. `"1.2.0"`) |
| `owner` | `str` | GitHub repository owner |
| `repo` | `str` | GitHub repository name |
| `app_name` | `str` | App name used for User-Agent header and temp file names |

### Methods

- **`check_for_update(token="") -> UpdateCheckResult`** — latest GitHub release;
  fields `has_update`, `latest_version`, `download_url`, `release_notes`, `error`;
  `.as_dict()` gives the legacy dict shape.
- **`download_update(url, token="", progress_callback=None) -> DownloadResult`** —
  downloads to a validated temp file; fields `path`, `error`.
- **`apply_update(path) -> bool`** — stage + atomic swap; **raises `UpdateError`** on
  failure (your current version is always left intact).
- **`restart_app()`** — exit the app so the new version takes over.
- **`clean_old_files(exe_path=None)`** *(static)* — restore a broken state, then remove
  `<exe>.old`, `<exe>.new`, `<exe>.update.log`.

### Exceptions

- `UpdateError` — user-presentable failure from `apply_update` (and future API).
  The provided message is safe to show in a dialog.

## Architecture

The package stays **stdlib-only**. Internally it is split into focused modules with
`UpdateService` as a thin facade:

```
github_updater/
  update_service.py    # public facade (keeps the API stable)
  semantics.py         # version comparison + app-name sanitizing (pure)
  release_check.py     # GitHub latest-release lookup (urllib)
  downloader.py        # asset download + exe validation
  windows_updater.py   # the safe EXE replacement (stage-first)
  models.py            # UpdateCheckResult / DownloadResult / UpdateError
```

## Testing

```bash
pip install -e . ruff pytest
ruff check src/ tests/
python -m pytest tests/ -q
```

101 tests cover version semantics, the GitHub check/download flows, every
validation- and failure path of the safe apply, exact CRLF helper files, self-
healing recovery, and - on Windows - a real `cmd /c` swap that proves the batch
replaces the exe atomically.

## License

MIT - see [LICENSE](LICENSE).