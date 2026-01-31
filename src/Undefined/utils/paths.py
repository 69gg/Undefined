"""Common runtime paths."""

from pathlib import Path

DATA_DIR = Path("data")
CACHE_DIR = DATA_DIR / "cache"
RENDER_CACHE_DIR = CACHE_DIR / "render"
IMAGE_CACHE_DIR = CACHE_DIR / "images"
DOWNLOAD_CACHE_DIR = CACHE_DIR / "downloads"


def ensure_dir(path: Path) -> Path:
    """Ensure a directory exists and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
