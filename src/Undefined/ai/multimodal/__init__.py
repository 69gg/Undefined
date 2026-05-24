"""多模态分析子包。

对外稳定入口：``MultimodalAnalyzer``、``detect_media_type``、``get_media_mime_type``。
"""

from Undefined.ai.multimodal import constants as _constants

# 测试 monkeypatch 沿用的模块级私有常量，勿随意改名
_MEDIA_URL_CACHE_DIR = _constants._MEDIA_URL_CACHE_DIR
_MEDIA_URL_CACHE_TTL_SECONDS = _constants._MEDIA_URL_CACHE_TTL_SECONDS
_MEDIA_URL_CACHE_MAX_FILES = _constants._MEDIA_URL_CACHE_MAX_FILES
_MEDIA_URL_CACHE_CLEANUP_INTERVAL_SECONDS = (
    _constants._MEDIA_URL_CACHE_CLEANUP_INTERVAL_SECONDS
)
_MEDIA_URL_DOWNLOAD_TIMEOUT_SECONDS = _constants._MEDIA_URL_DOWNLOAD_TIMEOUT_SECONDS
_MEDIA_URL_DOWNLOAD_TMP_SUFFIX = _constants._MEDIA_URL_DOWNLOAD_TMP_SUFFIX

from Undefined.ai.multimodal.analyzer import MultimodalAnalyzer  # noqa: E402
from Undefined.ai.multimodal.detection import detect_media_type, get_media_mime_type  # noqa: E402

__all__ = [
    "MultimodalAnalyzer",
    "detect_media_type",
    "get_media_mime_type",
    "_MEDIA_URL_CACHE_CLEANUP_INTERVAL_SECONDS",
    "_MEDIA_URL_CACHE_DIR",
    "_MEDIA_URL_CACHE_MAX_FILES",
    "_MEDIA_URL_CACHE_TTL_SECONDS",
    "_MEDIA_URL_DOWNLOAD_TIMEOUT_SECONDS",
    "_MEDIA_URL_DOWNLOAD_TMP_SUFFIX",
]
