"""Mention token extraction and conditional stripping."""

from __future__ import annotations

import re
from dataclasses import dataclass

_MENTION_RE = re.compile(r"\[@(\d+)(?:\([^)]*\))?\]")
_TRAILING_WS_RE = re.compile(r"[ \t\u3000]+")


@dataclass(frozen=True)
class MentionToken:
    """A normalized `[@qq]` / `[@qq(name)]` span."""

    qq: str
    start: int
    end: int


@dataclass(frozen=True)
class MentionConsumeResult:
    """Result of consuming mention clauses from normalized text."""

    matched: bool
    stripped: str
    mentions: tuple[str, ...]
    mentions_all: tuple[str, ...]


def extract_mention_tokens(text: str) -> list[MentionToken]:
    """Parse mention tokens from already-normalized message text."""
    tokens: list[MentionToken] = []
    for match in _MENTION_RE.finditer(text):
        tokens.append(
            MentionToken(qq=str(match.group(1)), start=match.start(), end=match.end())
        )
    return tokens


def consume_mentions(text: str, clauses: list[str]) -> MentionConsumeResult:
    """Match mention clauses left-to-right and strip only consumed tokens.

    Each specific QQ clause consumes one unused token with that id.
    Each ``*`` clause consumes one unused token of any id.
    Trailing whitespace immediately after a consumed token is removed with it.
    Empty ``clauses`` means no mention condition: text is passed through.
    """
    tokens = extract_mention_tokens(text)
    all_qqs = tuple(token.qq for token in tokens)
    if not clauses:
        return MentionConsumeResult(
            matched=True,
            stripped=text,
            mentions=(),
            mentions_all=all_qqs,
        )

    used = [False] * len(tokens)
    matched_indices: list[int] = []
    matched_qqs: list[str] = []
    for raw_clause in clauses:
        clause = str(raw_clause).strip()
        if not clause:
            continue
        found: int | None = None
        if clause == "*":
            for index, _token in enumerate(tokens):
                if not used[index]:
                    found = index
                    break
        else:
            for index, token in enumerate(tokens):
                if not used[index] and token.qq == clause:
                    found = index
                    break
        if found is None:
            return MentionConsumeResult(
                matched=False,
                stripped=text,
                mentions=(),
                mentions_all=all_qqs,
            )
        used[found] = True
        matched_indices.append(found)
        matched_qqs.append(tokens[found].qq)

    stripped = text
    for index in sorted(matched_indices, reverse=True):
        token = tokens[index]
        end = token.end
        ws_match = _TRAILING_WS_RE.match(stripped, end)
        if ws_match is not None:
            end = ws_match.end()
        stripped = stripped[: token.start] + stripped[end:]

    return MentionConsumeResult(
        matched=True,
        stripped=stripped,
        mentions=tuple(matched_qqs),
        mentions_all=all_qqs,
    )
