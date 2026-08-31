# github-updater

Shared GitHub release updater for Python desktop applications.

> **2026-08:** The repository was renamed from `Python_Units` to `github_updater`.
> The old URL `https://github.com/reserve85/Python_Units.git` still works via a
> GitHub redirect, so existing installs keep working without changes.

Provides a single `UpdateService` class that can check a GitHub repository for new releases, download update assets, and apply EXE updates via a Windows batch script — used by both **Movies & Series Autosort** and **MusicSceneReleaser**.

## Installation

```bash
pip install git+https://github.com/reserve85/github_updater.git
```

Or pin to a specific tag:

```bash
pip install git+https://github.com/reserve85/github_updater.git@v1.1.0
```

## Usage

```python
from github_updater import UpdateService

# Create service with your app's metadata
svc = UpdateService(
    current_version="1.2.0",
    owner="reserve85",
    repo="MyApp",
    app_name="MyApp",
)

# Check for updates
result = svc.check_for_update(token="ghp_xxx")
if result["has_update"]:
    path = svc.download_update(result["download_url"], token="ghp_xxx")
    if path and svc.apply_update(path):
        svc.restart_app()
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

- **`check_for_update(token) -> dict`** — Check GitHub for the latest release. Returns `has_update`, `latest_version`, `download_url`, `release_notes`, `error`.
- **`download_update(url, token, progress_callback) -> str`** — Download the update asset to a temp file. Returns the file path or empty string.
- **`apply_update(downloaded_path) -> bool`** — Replace the running EXE via a detached batch script (Windows only, frozen apps only).
- **`restart_app()`** — Exit the app so the user can restart with the new version.
- **`clean_old_files(exe_path)`** *(static)* — Remove leftover `.old` backup files from a previous update.
- **`_is_newer(latest, current) -> bool`** *(static)* — Compare semver strings.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
