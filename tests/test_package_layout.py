"""打包布局与模块结构回归测试。"""

from __future__ import annotations

from pathlib import Path

import Undefined


def test_py_typed_marker_exists() -> None:
    pkg_root = Path(Undefined.__file__).resolve().parent
    marker = pkg_root / "py.typed"
    assert marker.is_file(), "src/Undefined/py.typed must exist for PEP 561"


def test_py_typed_declared_in_pyproject() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'src/Undefined/py.typed" = "Undefined/py.typed"' in pyproject


def test_no_shadowed_monolith_modules() -> None:
    """禁止 foo.py 与 foo/ 包目录并存（会导致一份实现成为不可达死代码）。"""
    pkg_root = Path(Undefined.__file__).resolve().parent
    violations: list[str] = []
    for path in pkg_root.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        package_dir = path.with_suffix("")
        if package_dir.is_dir() and (package_dir / "__init__.py").is_file():
            violations.append(str(path.relative_to(pkg_root)))
    assert violations == [], f"shadowed monolith modules: {violations}"
