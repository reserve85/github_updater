"""github_updater — shared GitHub release updater for Python desktop apps."""

from github_updater.models import DownloadResult, UpdateCheckResult, UpdateError
from github_updater.update_service import UpdateService

__all__ = [
    "UpdateService",
    "UpdateCheckResult",
    "DownloadResult",
    "UpdateError",
]
__version__ = "1.2.0"
