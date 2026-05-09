from __future__ import annotations

from Undefined.bilibili.danmaku import parse_danmaku_segment


def _varint(value: int) -> bytes:
    chunks: list[int] = []
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            chunks.append(byte | 0x80)
        else:
            chunks.append(byte)
            return bytes(chunks)


def _field_varint(number: int, value: int) -> bytes:
    return _varint((number << 3) | 0) + _varint(value)


def _field_bytes(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _elem(
    *,
    progress_ms: int,
    content: str,
    dmid: int = 1,
    ctime: int = 100,
) -> bytes:
    return b"".join(
        [
            _field_varint(1, dmid),
            _field_varint(2, progress_ms),
            _field_varint(3, 1),
            _field_varint(5, 16777215),
            _field_bytes(6, b"hash"),
            _field_bytes(7, content.encode()),
            _field_varint(8, ctime),
            _field_varint(9, 6),
            _field_varint(11, 0),
            _field_bytes(12, str(dmid).encode()),
            _field_bytes(99, b"unknown"),
        ]
    )


def test_parse_danmaku_segment_reads_repeated_elems() -> None:
    payload = b"".join(
        [
            _field_bytes(1, _elem(progress_ms=2000, content="第二条", dmid=2)),
            _field_varint(2, 0),
            _field_bytes(1, _elem(progress_ms=1000, content="第一条", dmid=1)),
        ]
    )

    items = parse_danmaku_segment(payload)

    assert [item.content for item in items] == ["第二条", "第一条"]
    assert items[0].progress_ms == 2000
    assert items[0].dmid == "2"
    assert items[0].mid_hash == "hash"
    assert items[0].color == 16777215


def test_parse_danmaku_segment_skips_empty_content() -> None:
    payload = _field_bytes(1, _elem(progress_ms=1000, content=""))

    assert parse_danmaku_segment(payload) == []
