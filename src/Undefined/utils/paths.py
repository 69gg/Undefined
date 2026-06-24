"""Common runtime paths."""

from pathlib import Path

PACKAGE_ROOT: Path = Path(__file__).resolve().parent.parent

DATA_DIR: Path = Path("data")
HISTORY_DIR: Path = DATA_DIR / "history"
CACHE_DIR: Path = DATA_DIR / "cache"
RENDER_CACHE_DIR: Path = CACHE_DIR / "render"
IMAGE_CACHE_DIR: Path = CACHE_DIR / "images"
ATTACHMENT_CACHE_DIR: Path = CACHE_DIR / "attachments"
FORWARD_SNAPSHOT_CACHE_DIR: Path = CACHE_DIR / "forward_snapshots"
DOWNLOAD_CACHE_DIR: Path = CACHE_DIR / "downloads"
TEXT_FILE_CACHE_DIR: Path = CACHE_DIR / "text_files"
URL_FILE_CACHE_DIR: Path = CACHE_DIR / "url_files"
WEBUI_FILE_CACHE_DIR: Path = CACHE_DIR / "webui_files"
ATTACHMENT_REGISTRY_FILE: Path = DATA_DIR / "attachment_registry.json"
WEBCHAT_DIR: Path = DATA_DIR / "webchat"
WEBCHAT_CONVERSATIONS_DIR: Path = WEBCHAT_DIR / "conversations"
WEBCHAT_MIGRATION_MARKER_FILE: Path = WEBCHAT_DIR / "legacy_private_42_migrated.json"


def ensure_dir(path: Path) -> Path:
    """Ensure a directory exists and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


# Cognitive Memory
COGNITIVE_DIR: Path = DATA_DIR / "cognitive"
COGNITIVE_CHROMADB_DIR: Path = COGNITIVE_DIR / "chromadb"
COGNITIVE_PROFILES_DIR: Path = COGNITIVE_DIR / "profiles"
COGNITIVE_PROFILES_USERS_DIR: Path = COGNITIVE_PROFILES_DIR / "users"
COGNITIVE_PROFILES_GROUPS_DIR: Path = COGNITIVE_PROFILES_DIR / "groups"
COGNITIVE_PROFILES_HISTORY_DIR: Path = COGNITIVE_PROFILES_DIR / "history"
COGNITIVE_QUEUES_DIR: Path = COGNITIVE_DIR / "queues"
COGNITIVE_QUEUES_PENDING_DIR: Path = COGNITIVE_QUEUES_DIR / "pending"
COGNITIVE_QUEUES_PROCESSING_DIR: Path = COGNITIVE_QUEUES_DIR / "processing"
COGNITIVE_QUEUES_FAILED_DIR: Path = COGNITIVE_QUEUES_DIR / "failed"

# Meme Library
MEMES_DIR: Path = DATA_DIR / "memes"
MEMES_BLOBS_DIR: Path = MEMES_DIR / "blobs"
MEMES_PREVIEWS_DIR: Path = MEMES_DIR / "previews"
MEMES_DB_PATH: Path = MEMES_DIR / "memes.sqlite3"
MEMES_CHROMADB_DIR: Path = MEMES_DIR / "chromadb"
MEMES_QUEUES_DIR: Path = MEMES_DIR / "queues"
MEMES_QUEUES_PENDING_DIR: Path = MEMES_QUEUES_DIR / "pending"
MEMES_QUEUES_PROCESSING_DIR: Path = MEMES_QUEUES_DIR / "processing"
MEMES_QUEUES_FAILED_DIR: Path = MEMES_QUEUES_DIR / "failed"
