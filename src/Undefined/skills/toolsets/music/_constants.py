"""Shared lxmusic2api provider and quality constants."""

from __future__ import annotations

from typing import Final


PROVIDER_VALUES: Final[frozenset[str]] = frozenset({"kw", "kg", "tx", "wy", "mg"})
SOURCE_VALUES: Final[frozenset[str]] = PROVIDER_VALUES | {"all"}
QUALITY_VALUES: Final[frozenset[str]] = frozenset(
    {"flac24bit", "flac", "wav", "ape", "320k", "192k", "128k"}
)

PROVIDER_LABELS: Final[dict[str, str]] = {
    "kw": "酷我",
    "kg": "酷狗",
    "tx": "QQ 音乐",
    "wy": "网易云",
    "mg": "咪咕",
}

QUALITY_LABELS: Final[dict[str, str]] = {
    "flac24bit": "24-bit FLAC",
    "flac": "FLAC",
    "wav": "WAV",
    "ape": "APE",
    "320k": "320 kbps",
    "192k": "192 kbps",
    "128k": "128 kbps",
}
