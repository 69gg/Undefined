"""Resource loading helpers."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path
import shutil
import tempfile


def _candidate_paths(relative_path: str) -> list[Path]:
    module_path = Path(__file__).resolve()
    package_root = module_path.parents[1]
    candidates = [
        package_root / relative_path,
        package_root.parent / relative_path,
        package_root.parent.parent / relative_path,
        Path.cwd() / relative_path,
    ]
    return candidates


_EXTRACTED_FILES: dict[str, Path] = {}


def resolve_resource_path(relative_path: str) -> Path:
    if relative_path in _EXTRACTED_FILES:
        cached = _EXTRACTED_FILES[relative_path]
        if cached.exists():
            return cached
    try:
        base = resources.files("Undefined")
        candidate = base.joinpath(relative_path)
        if candidate.is_file():
            with resources.as_file(candidate) as real_path:
                tmp_root = Path(tempfile.gettempdir()) / "Undefined-resources"
                target = tmp_root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(real_path, target)
                _EXTRACTED_FILES[relative_path] = target
                return target
    except Exception:
        pass

    for path in _candidate_paths(relative_path):
        if path.is_file():
            return path

    raise FileNotFoundError(relative_path)


@lru_cache(maxsize=128)
def read_text_resource(relative_path: str, encoding: str = "utf-8") -> str:
    """Read a text resource with multiple fallbacks.

    Priority:
    1) Package resources (if packaged).
    2) Relative to package and common repo layouts.
    3) Current working directory.
    """
    try:
        base = resources.files("Undefined")
        candidate = base.joinpath(relative_path)
        if candidate.is_file():
            return candidate.read_text(encoding=encoding)
    except Exception:
        pass

    for path in _candidate_paths(relative_path):
        if path.is_file():
            return path.read_text(encoding=encoding)

    raise FileNotFoundError(relative_path)
