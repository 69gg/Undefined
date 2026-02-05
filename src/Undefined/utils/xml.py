"""Minimal XML escaping helpers."""

from __future__ import annotations

from xml.sax.saxutils import escape


def escape_xml_text(value: str) -> str:
    return escape(value, {'"': "&quot;", "'": "&apos;"})


def escape_xml_attr(value: object) -> str:
    text = "" if value is None else str(value)
    return escape(text, {'"': "&quot;", "'": "&apos;"})
