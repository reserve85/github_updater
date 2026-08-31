"""Asset downloader - network logic for ``UpdateService.download_update``.

Downloads the release asset to a named temp file and validates a Windows exe
by its ``MZ`` header. Returns a typed :class:`~github_updater.models.DownloadResult`.
"""

from __future__ import annotations

import logging
import os
import tempfile
from urllib.request import Request, urlopen

from github_updater.models import DownloadResult

logger = logging.getLogger(__name__)


def download_update(
    download_url: str,
    token: str,
    app_name: str,
    progress_callback=None,
) -> DownloadResult:
    """Download an update asset to a temp file.

    Args:
        download_url: The asset URL to download.
        token: GitHub token for authenticated (non-anonymous) downloads.
        app_name: Used for the User-Agent header.
        progress_callback: Optional ``callable(downloaded_bytes, total_bytes)``.

    Returns:
        ``DownloadResult`` with ``path`` set to the validated temp file on
        success, or ``error`` describing the failure (and empty ``path``).
    """
    headers = {
        "User-Agent": app_name,
        # Anonymous asset downloads from public repos need the binary Accept
        # header, otherwise GitHub responds with the release JSON instead.
        "Accept": "application/octet-stream",
    }
    if token:
        if token.startswith("github_pat"):
            headers["Authorization"] = f"Bearer {token}"
        else:
            headers["Authorization"] = f"token {token}"

    try:
        req = Request(download_url, headers=headers)
        with urlopen(req, timeout=120) as response:
            total_size = int(response.headers.get("Content-Length", 0))
            suffix = ".zip" if ".zip" in download_url else ".exe"
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            os.close(tmp_fd)

            downloaded = 0
            with open(tmp_path, "wb") as fh:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(downloaded, total_size)

        if suffix in (".exe", ".bin"):
            header = _read_header(tmp_path, 2)
            if header != b"MZ":
                logger.warning("Downloaded file is not a valid exe (header: %s)", header)
                os.unlink(tmp_path)
                return DownloadResult(error="Downloaded file is not a valid executable")

        logger.info("Downloaded %d bytes to %s", downloaded, tmp_path)
        return DownloadResult(path=tmp_path)
    except Exception as exc:  # noqa: BLE001 - network robustness
        logger.exception("Download error: %s", exc)
        return DownloadResult(error=str(exc))


def _read_header(path: str, nbytes: int) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(nbytes)
