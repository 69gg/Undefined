from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

import Undefined.ai.prompts.file_includes as file_includes_module
from Undefined.ai.prompts import PromptBuilder
from Undefined.ai.prompts.file_includes import apply_prompt_file_includes
from Undefined.end_summary_storage import EndSummaryRecord
from Undefined.utils.io import (
    get_file_mtime_ns,
    read_text,
    set_file_mtime_ns,
    write_text,
)


class _FakeEndSummaryStorage:
    async def load(self) -> list[EndSummaryRecord]:
        return []


@pytest.mark.asyncio
async def test_apply_prompt_file_includes_replaces_multiple_slots_once(
    tmp_path: Path,
) -> None:
    p0_path = tmp_path / "p0.xml"
    p2_path = tmp_path / "p2.xml"
    p0_path.write_text(
        '<private level="P0">alpha</private>\n'
        "<!-- undefined:prompt-file-include:p2 -->",
        encoding="utf-8",
    )
    p2_path.write_text('<private level="P2">beta</private>', encoding="utf-8")
    prompt = (
        "<system>\n"
        "  <!-- undefined:prompt-file-include:p0 -->\n"
        "  <middle />\n"
        "  <!-- undefined:prompt-file-include:p1 -->\n"
        "  <!-- undefined:prompt-file-include:p2 -->\n"
        "</system>\n"
    )

    result = await apply_prompt_file_includes(
        prompt,
        {"p0": str(p0_path), "p2": str(p2_path)},
    )

    assert '<private level="P0">alpha</private>' in result
    assert '<private level="P2">beta</private>' in result
    assert result.index('level="P0"') < result.index("<middle")
    assert result.index("<middle") < result.index('level="P2"')
    assert "prompt-file-include:p1" not in result
    assert result.count("<!-- undefined:prompt-file-include:p2 -->") == 1


@pytest.mark.asyncio
async def test_apply_prompt_file_includes_caches_by_path_and_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    include_path = tmp_path / "cached.xml"
    await write_text(include_path, "<private>first</private>")
    prompt = "<system>\n<!-- undefined:prompt-file-include:p0 -->\n</system>"
    read_text_mock = AsyncMock(wraps=read_text)
    monkeypatch.setattr(file_includes_module, "read_text", read_text_mock)

    first = await apply_prompt_file_includes(prompt, {"p0": str(include_path)})
    second = await apply_prompt_file_includes(prompt, {"p0": str(include_path)})

    assert "<private>first</private>" in first
    assert second == first
    assert read_text_mock.await_count == 1

    previous_mtime_ns = await get_file_mtime_ns(include_path)
    await write_text(include_path, "<private>updated</private>")
    changed_mtime_ns = previous_mtime_ns + 1_000_000_000
    await set_file_mtime_ns(include_path, changed_mtime_ns)

    updated = await apply_prompt_file_includes(prompt, {"p0": str(include_path)})

    assert "<private>updated</private>" in updated
    assert "<private>first</private>" not in updated
    assert read_text_mock.await_count == 2


@pytest.mark.asyncio
async def test_apply_prompt_file_includes_warns_for_unknown_slots(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    include_path = tmp_path / "p0.xml"
    include_path.write_text("<private>configured</private>", encoding="utf-8")
    prompt = "<system>\n<!-- undefined:prompt-file-include:p0 -->\n</system>"

    with caplog.at_level(logging.WARNING):
        result = await apply_prompt_file_includes(
            prompt,
            {"p0": str(include_path), "custom": "ignored.xml"},
        )

    assert "<private>configured</private>" in result
    assert "未知的文件插槽已忽略: custom" in caplog.text


@pytest.mark.asyncio
async def test_apply_prompt_file_includes_warns_and_skips_unreadable_files(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    invalid_path = tmp_path / "invalid.xml"
    invalid_path.write_bytes(b"\xff")
    missing_path = tmp_path / "missing.xml"
    prompt = (
        "<system>\n"
        "<!-- undefined:prompt-file-include:p0 -->\n"
        "<!-- undefined:prompt-file-include:p1 -->\n"
        "</system>\n"
    )

    with caplog.at_level(logging.WARNING):
        result = await apply_prompt_file_includes(
            prompt,
            {"p0": str(missing_path), "p1": str(invalid_path)},
        )

    assert "prompt-file-include" not in result
    assert "文件插槽不存在" in caplog.text
    assert "文件插槽读取失败" in caplog.text
    assert "\ufffd" not in result


@pytest.mark.asyncio
async def test_prompt_builder_hot_reloads_include_content_and_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_path = tmp_path / "first.xml"
    second_path = tmp_path / "second.xml"
    await write_text(first_path, "<private>first</private>")
    await write_text(second_path, "<private>second-path</private>")
    runtime_config = SimpleNamespace(
        prompt_file_includes={"p0": str(first_path)},
        keyword_reply_enabled=False,
        repeat_enabled=False,
        inverted_question_enabled=False,
        cognitive=SimpleNamespace(enabled=False, recent_end_summaries_inject_k=0),
    )
    builder = PromptBuilder(
        bot_qq=0,
        memory_storage=None,
        end_summary_storage=cast(Any, _FakeEndSummaryStorage()),
        runtime_config_getter=lambda: runtime_config,
    )

    async def _fake_load_system_prompt(*, nagaagent_active: bool | None = None) -> str:
        _ = nagaagent_active
        return "<system>\n<!-- undefined:prompt-file-include:p0 -->\n</system>"

    async def _fake_load_each_rules() -> str:
        return ""

    monkeypatch.setattr(builder, "_load_system_prompt", _fake_load_system_prompt)
    monkeypatch.setattr(builder, "_load_each_rules", _fake_load_each_rules)

    first_messages = await builder.build_messages("<message>first</message>")
    assert "<private>first</private>" in str(first_messages[0]["content"])

    previous_mtime_ns = await get_file_mtime_ns(first_path)
    await write_text(first_path, "<private>updated-content</private>")
    changed_mtime_ns = previous_mtime_ns + 1_000_000_000
    await set_file_mtime_ns(first_path, changed_mtime_ns)
    updated_messages = await builder.build_messages("<message>updated</message>")
    assert "<private>updated-content</private>" in str(updated_messages[0]["content"])
    assert "<private>first</private>" not in str(updated_messages[0]["content"])

    runtime_config.prompt_file_includes = {"p0": str(second_path)}
    switched_messages = await builder.build_messages("<message>switched</message>")
    assert "<private>second-path</private>" in str(switched_messages[0]["content"])
