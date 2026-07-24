from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol, cast

import httpx
import pytest

from Undefined.skills.toolsets import ToolSetRegistry
from Undefined.skills.toolsets.music._track_refs import (
    MUSIC_TRACK_STORE_CONTEXT_KEY,
    MusicTrackReferenceError,
    MusicTrackReferenceStore,
)
from Undefined.skills.toolsets.music._tools import (
    execute_browse_playlists,
    execute_browse_rankings,
    execute_find_song_matches,
    execute_get_audio,
    execute_get_comments,
    execute_get_cover,
    execute_get_hot_search,
    execute_get_lyrics,
    execute_search_playlists,
    execute_search_songs,
)


class ExecuteTool(Protocol):
    async def __call__(self, args: dict[str, Any], context: dict[str, Any]) -> str: ...


@dataclass(slots=True)
class FakeRecord:
    uid: str
    display_name: str
    mime_type: str | None


class FakeAttachmentRegistry:
    def __init__(self) -> None:
        self.bytes_calls: list[dict[str, object]] = []
        self.url_calls: list[dict[str, object]] = []

    async def register_bytes(
        self,
        scope_key: str,
        content: bytes,
        *,
        kind: str,
        display_name: str,
        source_kind: str,
        source_ref: str = "",
        mime_type: str | None = None,
        segment_data: Mapping[str, str] | None = None,
        semantic_kind: str = "",
        description: str = "",
    ) -> FakeRecord:
        self.bytes_calls.append(
            {
                "scope_key": scope_key,
                "content": content,
                "kind": kind,
                "display_name": display_name,
                "source_kind": source_kind,
                "source_ref": source_ref,
                "mime_type": mime_type,
                "segment_data": dict(segment_data or {}),
                "semantic_kind": semantic_kind,
                "description": description,
            }
        )
        return FakeRecord("file_audio123", display_name, mime_type)

    async def register_remote_url(
        self,
        scope_key: str,
        url: str,
        *,
        kind: str,
        display_name: str | None = None,
        source_kind: str = "remote_url",
        source_ref: str = "",
        segment_data: Mapping[str, str] | None = None,
    ) -> FakeRecord:
        self.url_calls.append(
            {
                "scope_key": scope_key,
                "url": url,
                "kind": kind,
                "display_name": display_name,
                "source_kind": source_kind,
                "source_ref": source_ref,
                "segment_data": dict(segment_data or {}),
            }
        )
        return FakeRecord("pic_cover123", display_name or "cover.jpg", "image/jpeg")


class ChunkedStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


TRACK: dict[str, object] = {
    "id": "kg_song/hash",
    "source": "kg",
    "name": "Test Song",
    "singer": "Test Singer",
    "interval": "03:20",
    "albumName": "Test Album",
    "picUrl": None,
    "qualities": [{"type": "320k", "size": "8 MB", "hash": "hash"}],
    "sourceData": {"songId": "song/id", "hash": "hash"},
}

MUSIC_TOOL_NAMES = {
    "music.search_songs",
    "music.search_playlists",
    "music.get_hot_search",
    "music.browse_playlists",
    "music.browse_rankings",
    "music.get_lyrics",
    "music.get_cover",
    "music.get_comments",
    "music.find_song_matches",
    "music.get_audio",
}


def _context(
    client: httpx.AsyncClient,
    *,
    registry: FakeAttachmentRegistry | None = None,
    api_key: str = "test-key",
    max_size_mb: int = 1,
    base_url: str = "https://music.example.test",
) -> dict[str, Any]:
    return {
        "runtime_config": SimpleNamespace(
            lxmusic2api_base_url=base_url,
            lxmusic2api_api_key=api_key,
            network_request_timeout=5.0,
            attachment_remote_download_max_size_mb=max_size_mb,
        ),
        "lxmusic2api_http_client": client,
        MUSIC_TRACK_STORE_CONTEXT_KEY: MusicTrackReferenceStore(
            reference_namespace="test"
        ),
        "attachment_registry": registry,
        "get_scope_from_context": lambda _context: "group:100",
    }


def _success_handler(
    assertions: Callable[[httpx.Request], None],
    *,
    data: object | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        assertions(request)
        return httpx.Response(
            200, json={"data": {"ok": True} if data is None else data}
        )

    return handler


def test_music_registry_exposes_only_user_facing_tools() -> None:
    toolsets_root = (
        Path(__file__).parents[1] / "src" / "Undefined" / "skills" / "toolsets"
    )
    registry = ToolSetRegistry(toolsets_root)
    names = {
        str(schema["function"]["name"])
        for schema in registry.get_tools_schema()
        if str(schema["function"]["name"]).startswith("music.")
    }

    assert names == MUSIC_TOOL_NAMES
    assert not any("download" in name or "job" in name for name in names)


def test_music_tool_descriptions_define_audio_delivery_contract() -> None:
    toolsets_root = (
        Path(__file__).parents[1] / "src" / "Undefined" / "skills" / "toolsets"
    )
    registry = ToolSetRegistry(toolsets_root)
    functions = {
        str(schema["function"]["name"]): schema["function"]
        for schema in registry.get_tools_schema()
    }

    search_description = str(functions["music.search_songs"]["description"])
    assert "不下载音频、不注册附件，也不向用户发送任何内容" in search_description
    assert "不要固定取第一条或固定平台" in search_description
    assert "匹配明确时无需询问" in search_description
    assert "仅当没有结果或无法可靠判断原唱/目标版本时才询问用户" in search_description
    assert "传给 music.get_audio" in search_description
    assert "仅搜索成功不代表发歌任务完成" in search_description
    assert "track_ref" in search_description

    audio_function = functions["music.get_audio"]
    audio_description = str(audio_function["description"])
    assert "本工具本身绝不会向用户发送消息或文件" in audio_description
    assert "灵活选择其中实际列出的最高可用值" in audio_description
    assert "调用 messages.send_message" in audio_description
    assert "调用 messages.send_voice" in audio_description
    assert "发送工具成功后才可结束" in audio_description
    delivery_description = str(
        audio_function["parameters"]["properties"]["delivery"]["description"]
    )
    assert "不发送" in delivery_description
    quality_description = str(
        audio_function["parameters"]["properties"]["quality"]["description"]
    )
    assert "不要机械省略或固定填写" in quality_description
    assert "候选的 qualities" in quality_description

    for name in (
        "music.get_lyrics",
        "music.get_cover",
        "music.get_comments",
        "music.find_song_matches",
        "music.get_audio",
    ):
        parameters = functions[name]["parameters"]
        assert parameters["required"] == ["track_ref"]
        assert "track_ref" in parameters["properties"]
        assert "track" not in parameters["properties"]


def test_music_tools_are_not_shared_with_subagents() -> None:
    music_root = (
        Path(__file__).parents[1]
        / "src"
        / "Undefined"
        / "skills"
        / "toolsets"
        / "music"
    )

    assert list(music_root.rglob("callable.json")) == []


def _track_variant(track_id: str, *, name: str = "Test Song") -> dict[str, object]:
    track = dict(TRACK)
    track["id"] = track_id
    track["name"] = name
    track["sourceData"] = {"songId": track_id, "hash": f"hash-{track_id}"}
    return track


def test_music_track_reference_store_deduplicates_and_copies_tracks() -> None:
    store = MusicTrackReferenceStore(reference_namespace="task-a")
    original = _track_variant("kg_song-a")

    reference = store.register(original)
    cast(dict[str, object], original["sourceData"])["hash"] = "mutated"

    resolved = store.resolve(reference)
    assert reference == "mtrk_task-a_1"
    assert cast(dict[str, object], resolved["sourceData"])["hash"] == ("hash-kg_song-a")

    resolved["name"] = "mutated copy"
    assert store.resolve(reference)["name"] == "Test Song"

    updated = _track_variant("kg_song-a", name="Updated Song")
    assert store.register(updated) == reference
    assert store.resolve(reference)["name"] == "Updated Song"


def test_music_track_reference_store_evicts_least_recently_used_track() -> None:
    store = MusicTrackReferenceStore(max_entries=2, reference_namespace="task-a")
    first = store.register(_track_variant("kg_first"))
    second = store.register(_track_variant("kg_second"))
    assert store.resolve(first)["id"] == "kg_first"

    third = store.register(_track_variant("kg_third"))

    assert store.resolve(first)["id"] == "kg_first"
    assert store.resolve(third)["id"] == "kg_third"
    with pytest.raises(MusicTrackReferenceError, match="无效、已淘汰"):
        store.resolve(second)


def test_music_track_references_do_not_collide_across_tasks() -> None:
    first_store = MusicTrackReferenceStore(reference_namespace="task-a")
    second_store = MusicTrackReferenceStore(reference_namespace="task-b")
    first_reference = first_store.register(_track_variant("kg_first"))
    second_store.register(_track_variant("kg_second"))

    with pytest.raises(MusicTrackReferenceError, match="不属于当前任务"):
        second_store.resolve(first_reference)


@pytest.mark.parametrize(
    ("tool", "args", "method", "path", "query", "body"),
    [
        (
            execute_search_songs,
            {"query": "夜曲", "source": "all", "page": 2, "limit": 10},
            "GET",
            "/v1/search/tracks",
            {"q": "夜曲", "source": "all", "page": "2", "limit": "10"},
            None,
        ),
        (
            execute_search_playlists,
            {"query": "学习", "source": "wy"},
            "GET",
            "/v1/search/playlists",
            {"q": "学习", "source": "wy", "page": "1", "limit": "20"},
            None,
        ),
        (
            execute_get_hot_search,
            {"source": "tx"},
            "GET",
            "/v1/search/hot",
            {"source": "tx"},
            None,
        ),
        (
            execute_browse_playlists,
            {"action": "tags", "source": "kg"},
            "GET",
            "/v1/playlists/kg/tags",
            {},
            None,
        ),
        (
            execute_browse_playlists,
            {
                "action": "list",
                "source": "kw",
                "tag_id": "tag/1",
                "sort_id": "new",
                "page": 3,
            },
            "GET",
            "/v1/playlists/kw",
            {"tagId": "tag/1", "sortId": "new", "page": "3"},
            None,
        ),
        (
            execute_browse_playlists,
            {"action": "detail", "source": "wy", "playlist_id": "list/a"},
            "GET",
            "/v1/playlists/wy/list%2Fa",
            {"page": "1"},
            None,
        ),
        (
            execute_browse_rankings,
            {"action": "list", "source": "mg"},
            "GET",
            "/v1/leaderboards/mg",
            {},
            None,
        ),
        (
            execute_browse_rankings,
            {"action": "detail", "source": "tx", "ranking_id": "top/1"},
            "GET",
            "/v1/leaderboards/tx/top%2F1",
            {"page": "1"},
            None,
        ),
        (
            execute_get_lyrics,
            {"track": TRACK},
            "POST",
            "/v1/tracks/lyrics",
            {},
            {"track": TRACK},
        ),
        (
            execute_get_comments,
            {"track": TRACK, "mode": "hot", "page": 2, "limit": 5},
            "POST",
            "/v1/tracks/comments",
            {},
            {"track": TRACK, "kind": "hot", "page": 2, "limit": 5},
        ),
        (
            execute_get_comments,
            {"track": TRACK, "mode": "replies", "comment_id": "comment/1"},
            "POST",
            "/v1/tracks/comments/comment%2F1/replies",
            {},
            {"track": TRACK, "page": 1, "limit": 20},
        ),
        (
            execute_find_song_matches,
            {"track": TRACK},
            "POST",
            "/v1/tracks/matches",
            {},
            {"track": TRACK},
        ),
    ],
)
async def test_json_tool_routes(
    tool: ExecuteTool,
    args: dict[str, Any],
    method: str,
    path: str,
    query: dict[str, str],
    body: dict[str, object] | None,
) -> None:
    def assertions(request: httpx.Request) -> None:
        assert request.method == method
        assert request.url.raw_path.decode().split("?", 1)[0] == path
        assert dict(request.url.params) == query
        if body is not None:
            assert json.loads(request.content) == body

    response_data: object = {"ok": True}
    if tool is execute_search_songs:
        response_data = {"items": []}
    elif tool is execute_find_song_matches:
        response_data = []
    elif (
        tool in {execute_browse_playlists, execute_browse_rankings}
        and args.get("action") == "detail"
    ):
        response_data = {"list": []}

    transport = httpx.MockTransport(_success_handler(assertions, data=response_data))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await tool(args, _context(client))

    assert json.loads(result) == response_data


async def test_search_reference_restores_exact_track_for_followup_tool() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path == "/v1/search/tracks"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "items": [TRACK],
                        "page": 1,
                        "limit": 20,
                        "total": 1,
                        "totalPages": 1,
                        "upstreamErrors": [],
                    }
                },
            )
        assert request.method == "POST"
        assert request.url.path == "/v1/tracks/lyrics"
        assert json.loads(request.content) == {"track": TRACK}
        return httpx.Response(200, json={"data": {"lyric": "test lyric"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        context = _context(client)
        search_result = json.loads(
            await execute_search_songs({"query": "Test Song"}, context)
        )
        candidate = search_result["items"][0]
        lyrics_result = await execute_get_lyrics(
            {"track_ref": candidate["track_ref"]}, context
        )

    assert candidate == {
        "track_ref": "mtrk_test_1",
        "name": "Test Song",
        "singer": "Test Singer",
        "albumName": "Test Album",
        "interval": "03:20",
        "source": "kg",
        "qualities": ["320k"],
    }
    assert "id" not in candidate
    assert "picUrl" not in candidate
    assert "sourceData" not in candidate
    assert json.loads(lyrics_result) == {"lyric": "test lyric"}


@pytest.mark.parametrize(
    ("tool", "args", "response_data", "result_field"),
    [
        (
            execute_browse_playlists,
            {"action": "detail", "source": "kg", "playlist_id": "playlist-1"},
            {"list": [TRACK], "page": 1},
            "list",
        ),
        (
            execute_browse_rankings,
            {"action": "detail", "source": "kg", "ranking_id": "ranking-1"},
            {"list": [TRACK], "page": 1},
            "list",
        ),
        (
            execute_find_song_matches,
            {"track": TRACK},
            [TRACK],
            None,
        ),
    ],
)
async def test_other_track_producers_return_compact_references(
    tool: ExecuteTool,
    args: dict[str, Any],
    response_data: object,
    result_field: str | None,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": response_data})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = json.loads(await tool(args, _context(client)))

    candidates = result if result_field is None else result[result_field]
    assert candidates[0] == {
        "track_ref": "mtrk_test_1",
        "name": "Test Song",
        "singer": "Test Singer",
        "albumName": "Test Album",
        "interval": "03:20",
        "source": "kg",
        "qualities": ["320k"],
    }


async def test_invalid_track_reference_does_not_call_music_service() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid track_ref must not make a request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_get_lyrics({"track_ref": "mtrk_999"}, _context(client))

    assert "track_ref 无效、已淘汰或不属于当前任务" in result
    assert "重新搜索歌曲" in result


async def test_invalid_track_reference_does_not_fall_back_to_legacy_track() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid track_ref must take precedence")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_get_lyrics(
            {"track_ref": "mtrk_999", "track": TRACK}, _context(client)
        )

    assert "track_ref 无效" in result


async def test_api_error_is_readable_and_does_not_expose_key() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "API Key 无效",
                    "requestId": "req-7",
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_search_songs({"query": "test"}, _context(client))

    assert "API Key 无效" in result
    assert "UNAUTHORIZED" in result
    assert "req-7" in result
    assert "test-key" not in result


async def test_success_response_must_be_json_data_envelope() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        invalid_json = await execute_get_hot_search({}, _context(client))

    def missing_data_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(missing_data_handler)
    ) as client:
        missing_data = await execute_get_hot_search({}, _context(client))

    assert "无效的 JSON" in invalid_json
    assert "缺少 data 字段" in missing_data


async def test_blank_api_key_disables_direct_execution_without_request() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("blank key must not make a request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_get_hot_search({}, _context(client, api_key=""))

    assert "音乐工具未启用" in result


async def test_network_timeout_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out with secret", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_get_hot_search({}, _context(client))

    assert result == "音乐服务调用失败：lxmusic2api 请求超时"


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://music.example.test",
        "https://user:secret@music.example.test",
        "https://music.example.test/v1",
    ],
)
async def test_invalid_base_url_is_rejected_without_request(base_url: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid base URL must not make a request")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_get_hot_search({}, _context(client, base_url=base_url))

    assert "lxmusic2api.base_url" in result


async def test_get_cover_supports_url_and_attachment_delivery() -> None:
    cover_url = "https://cdn.example.test/cover.jpg"

    def assertions(request: httpx.Request) -> None:
        assert request.url.path == "/v1/tracks/cover"
        assert json.loads(request.content) == {"track": TRACK}

    transport = httpx.MockTransport(
        _success_handler(assertions, data={"url": cover_url})
    )
    registry = FakeAttachmentRegistry()
    async with httpx.AsyncClient(transport=transport) as client:
        context = _context(client, registry=registry)
        url_result = await execute_get_cover(
            {"track": TRACK, "delivery": "url"}, context
        )
        attachment_result = await execute_get_cover({"track": TRACK}, context)

    assert json.loads(url_result) == {"url": cover_url}
    assert json.loads(attachment_result)["attachment"] == (
        '<attachment uid="pic_cover123"/>'
    )
    assert registry.url_calls[0]["scope_key"] == "group:100"
    assert registry.url_calls[0]["kind"] == "image"


async def test_get_audio_url_delivery_uses_resolver() -> None:
    resolved = {
        "url": "https://audio.example.test/song.mp3",
        "resolvedQuality": "320k",
        "qualityFallbackUsed": False,
        "sourceFallbackUsed": False,
        "track": TRACK,
    }

    def assertions(request: httpx.Request) -> None:
        assert request.url.path == "/v1/tracks/resolve"
        assert json.loads(request.content) == {
            "track": TRACK,
            "quality": "320k",
            "strictQuality": True,
        }

    transport = httpx.MockTransport(_success_handler(assertions, data=resolved))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await execute_get_audio(
            {
                "track": TRACK,
                "quality": "320k",
                "strict_quality": True,
                "delivery": "url",
            },
            _context(client),
        )

    payload = json.loads(result)
    assert payload == {
        "url": "https://audio.example.test/song.mp3",
        "resolvedQuality": "320k",
        "qualityFallbackUsed": False,
        "sourceFallbackUsed": False,
        "track": {
            "track_ref": "mtrk_test_1",
            "name": "Test Song",
            "singer": "Test Singer",
            "albumName": "Test Album",
            "interval": "03:20",
            "source": "kg",
            "qualities": ["320k"],
        },
    }


async def test_get_audio_normalizes_string_boolean_for_direct_invocation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["strictQuality"] is False
        assert "quality" not in body
        return httpx.Response(200, json={"data": {"url": "https://audio.test"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_get_audio(
            {"track": TRACK, "strict_quality": "false", "delivery": "url"},
            _context(client),
        )

    assert json.loads(result)["url"] == "https://audio.test"


async def test_get_audio_streams_and_registers_attachment() -> None:
    audio = b"audio-bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/tracks/stream"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "track": TRACK,
            "quality": "320k",
            "strictQuality": False,
        }
        return httpx.Response(
            200,
            headers={
                "content-type": "audio/mpeg",
                "content-length": str(len(audio)),
                "x-lxmusic2api-resolved-source": "kw",
                "x-lxmusic2api-requested-quality": "320k",
                "x-lxmusic2api-resolved-quality": "128k",
                "x-lxmusic2api-source-fallback-used": "true",
                "x-lxmusic2api-quality-fallback-used": "true",
            },
            content=audio,
        )

    registry = FakeAttachmentRegistry()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_get_audio(
            {"track": TRACK, "quality": "320k"},
            _context(client, registry=registry),
        )

    payload = json.loads(result)
    assert payload["attachment"] == '<attachment uid="file_audio123"/>'
    assert payload["bytes"] == len(audio)
    assert registry.bytes_calls[0]["content"] == audio
    assert registry.bytes_calls[0]["kind"] == "audio"
    assert registry.bytes_calls[0]["display_name"] == "Test Song - Test Singer.mp3"
    assert registry.bytes_calls[0]["semantic_kind"] == "music"
    description = str(registry.bytes_calls[0]["description"])
    assert "[音乐] 名称：Test Song" in description
    assert "歌手/作者：Test Singer" in description
    assert "专辑：Test Album" in description
    assert "平台：酷狗（kg） → 酷我（kw）（实际）" in description
    assert "音质：320 kbps（请求）→ 128 kbps（实际）" in description
    assert "回退：跨平台回退、音质降级" in description
    segment_data = cast(dict[str, str], registry.bytes_calls[0]["segment_data"])
    assert segment_data["resolved_source"] == "kw"
    assert segment_data["resolved_quality"] == "128k"
    assert segment_data["source_fallback_used"] == "true"
    assert segment_data["quality_fallback_used"] == "true"


async def test_get_audio_tolerates_missing_or_invalid_resolution_headers() -> None:
    audio = b"audio-bytes"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "audio/mpeg",
                "content-length": str(len(audio)),
                "x-lxmusic2api-resolved-source": "unsupported",
                "x-lxmusic2api-resolved-quality": "lossless",
                "x-lxmusic2api-source-fallback-used": "maybe",
            },
            content=audio,
        )

    registry = FakeAttachmentRegistry()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_get_audio(
            {"track": TRACK, "quality": "320k"},
            _context(client, registry=registry),
        )

    assert json.loads(result)["attachment"] == '<attachment uid="file_audio123"/>'
    description = str(registry.bytes_calls[0]["description"])
    assert "所选平台：酷狗（kg）（最终平台未报告）" in description
    assert "请求音质：320 kbps（最终音质未报告）" in description
    segment_data = cast(dict[str, str], registry.bytes_calls[0]["segment_data"])
    assert segment_data["selected_source"] == "kg"
    assert segment_data["requested_quality"] == "320k"
    assert "resolved_source" not in segment_data
    assert "resolved_quality" not in segment_data
    assert "source_fallback_used" not in segment_data


async def test_get_audio_rejects_content_length_over_limit() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "audio/mpeg",
                "content-length": str(2 * 1024 * 1024),
            },
            content=b"small",
        )

    registry = FakeAttachmentRegistry()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_get_audio(
            {"track": TRACK}, _context(client, registry=registry, max_size_mb=1)
        )

    assert "超过附件上限" in result
    assert registry.bytes_calls == []


async def test_get_audio_reports_json_stream_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            json={
                "error": {
                    "code": "AUDIO_UPSTREAM_ERROR",
                    "message": "音频上游暂时不可用",
                    "requestId": "req-audio",
                }
            },
        )

    registry = FakeAttachmentRegistry()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_get_audio(
            {"track": TRACK}, _context(client, registry=registry)
        )

    assert "音频上游暂时不可用" in result
    assert "AUDIO_UPSTREAM_ERROR" in result
    assert "req-audio" in result


async def test_get_audio_rejects_non_audio_content() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html>not audio</html>",
        )

    registry = FakeAttachmentRegistry()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_get_audio(
            {"track": TRACK}, _context(client, registry=registry)
        )

    assert "非音频内容" in result
    assert registry.bytes_calls == []


async def test_get_audio_enforces_streamed_byte_limit_without_header() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "audio/mpeg"},
            stream=ChunkedStream([b"a" * 700_000, b"b" * 700_000]),
        )

    registry = FakeAttachmentRegistry()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_get_audio(
            {"track": TRACK}, _context(client, registry=registry, max_size_mb=1)
        )

    assert "音频流超过附件上限" in result
    assert registry.bytes_calls == []


async def test_get_audio_requires_enabled_attachment_downloads() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("disabled attachment mode must not make a request")

    registry = FakeAttachmentRegistry()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await execute_get_audio(
            {"track": TRACK}, _context(client, registry=registry, max_size_mb=0)
        )

    assert "delivery 设为 url" in result
    assert registry.bytes_calls == []
