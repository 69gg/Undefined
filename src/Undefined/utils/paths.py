"""Common runtime paths."""

from pathlib import Path

DATA_DIR = Path("data")
CACHE_DIR = DATA_DIR / "cache"
RENDER_CACHE_DIR = CACHE_DIR / "render"
IMAGE_CACHE_DIR = CACHE_DIR / "images"
DOWNLOAD_CACHE_DIR = CACHE_DIR / "downloads"
TEXT_FILE_CACHE_DIR = CACHE_DIR / "text_files"
URL_FILE_CACHE_DIR = CACHE_DIR / "url_files"
WEBUI_FILE_CACHE_DIR = CACHE_DIR / "webui_files"


def ensure_dir(path: Path) -> Path:
    """Ensure a directory exists and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


# Cognitive Memory
COGNITIVE_DIR = DATA_DIR / "cognitive"
COGNITIVE_CHROMADB_DIR = COGNITIVE_DIR / "chromadb"
COGNITIVE_PROFILES_DIR = COGNITIVE_DIR / "profiles"
COGNITIVE_PROFILES_USERS_DIR = COGNITIVE_PROFILES_DIR / "users"
COGNITIVE_PROFILES_GROUPS_DIR = COGNITIVE_PROFILES_DIR / "groups"
COGNITIVE_PROFILES_HISTORY_DIR = COGNITIVE_PROFILES_DIR / "history"
COGNITIVE_QUEUES_DIR = COGNITIVE_DIR / "queues"
COGNITIVE_QUEUES_PENDING_DIR = COGNITIVE_QUEUES_DIR / "pending"
COGNITIVE_QUEUES_PROCESSING_DIR = COGNITIVE_QUEUES_DIR / "processing"
COGNITIVE_QUEUES_FAILED_DIR = COGNITIVE_QUEUES_DIR / "failed"
