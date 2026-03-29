from __future__ import annotations

from Undefined.arxiv.parser import (
    extract_arxiv_ids,
    extract_from_json_message,
    normalize_arxiv_id,
)


def test_normalize_arxiv_id_accepts_abs_pdf_and_prefix() -> None:
    assert normalize_arxiv_id("https://arxiv.org/abs/2501.01234v2") == "2501.01234v2"
    assert normalize_arxiv_id("https://arxiv.org/pdf/2501.01234.pdf") == "2501.01234"
    assert normalize_arxiv_id("arXiv:hep-th/9901001v3") == "hep-th/9901001v3"


def test_extract_arxiv_ids_requires_keyword_for_bare_new_style_id() -> None:
    assert extract_arxiv_ids("2501.01234") == []
    assert extract_arxiv_ids("看看 arxiv 2501.01234 和 arXiv:2501.01235") == [
        "2501.01235",
        "2501.01234",
    ]


def test_extract_from_json_message_recursively_scans_strings() -> None:
    segments = [
        {
            "type": "json",
            "data": {
                "data": (
                    '{"meta":{"detail_1":{"desc":"'
                    '论文链接 https://arxiv.org/abs/2501.01234v2"},"items":["arxiv:2501.01235"]}}'
                )
            },
        }
    ]

    assert extract_from_json_message(segments) == ["2501.01234v2", "2501.01235"]
