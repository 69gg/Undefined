from __future__ import annotations

from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def build_agent_description(agent_dir: Path, fallback: str = "") -> str:
    intro_path = agent_dir / "intro.md"
    generated_path = agent_dir / "intro.generated.md"

    intro_text = _read_text(intro_path)
    generated_text = _read_text(generated_path)

    if not intro_text and not generated_text:
        return fallback.strip()

    if generated_text:
        merged = intro_text.rstrip()
        if merged:
            merged += "\n\n---\n\n## 以下为Agent自我介绍\n\n"
        merged += generated_text.strip()
        return merged.strip()

    return intro_text.strip()
