"""只转换发送副本中的本地媒体字段，保留原始 CQ 文本和未知消息段。"""

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import url2pathname

from Undefined.attachments.segments import is_localish_path
from Undefined.attachments.render import _escape_cq_component
from Undefined.utils.common import CQ_PATTERN

_MEDIA_FIELDS = {
    "image": ("file",),
    "record": ("file",),
    "video": ("file", "thumb"),
    "file": ("file",),
}


def local_file_path(value: str) -> Path | None:
    if not is_localish_path(value):
        return None
    if value.startswith("file://"):
        uri = urlsplit(value)
        path = url2pathname(uri.path)
        if uri.netloc and uri.netloc != "localhost":
            path = f"//{uri.netloc}{path}"
        return Path(path)
    return Path(value)


def _unescape_cq(value: str) -> str:
    return (
        value.replace("&#91;", "[")
        .replace("&#93;", "]")
        .replace("&#44;", ",")
        .replace("&amp;", "&")
    )


def map_file_references(
    action: str, params: dict[str, Any], replace: Callable[[str], str]
) -> dict[str, Any]:
    """转换已知媒体字段，replace 可仅收集来源；永不修改调用者输入。"""

    def message(value: Any) -> Any:
        if isinstance(value, str):

            def cq(match: Any) -> str:
                kind, args = match.group(1), match.group(2)
                fields = _MEDIA_FIELDS.get(kind)
                if fields is None:
                    return str(match.group(0))
                parts = args.split(",")
                changed = False
                filename: str | None = None
                for index, part in enumerate(parts):
                    key, sep, raw = part.partition("=")
                    if sep and key in fields:
                        original = _unescape_cq(raw)
                        updated = replace(original)
                        if updated != original:
                            changed = True
                            parts[index] = f"{key}={_escape_cq_component(updated)}"
                            path = local_file_path(original)
                            if kind == "file" and key == "file" and path is not None:
                                filename = path.name
                if not changed:
                    return str(match.group(0))
                if filename and not any(part.startswith("name=") for part in parts):
                    parts.append(f"name={_escape_cq_component(filename)}")
                return f"[CQ:{kind},{','.join(parts)}]"

            return CQ_PATTERN.sub(cq, value)
        if isinstance(value, list):
            return [message(item) for item in value]
        if isinstance(value, dict):
            result = deepcopy(value)
            kind = result.get("type")
            data = result.get("data")
            if isinstance(data, dict):
                for field in _MEDIA_FIELDS.get(str(kind), ()):
                    if isinstance(data.get(field), str):
                        original = data[field]
                        data[field] = replace(original)
                        if (
                            kind == "file"
                            and data[field] != original
                            and "name" not in data
                        ):
                            path = local_file_path(original)
                            if path is not None:
                                data["name"] = path.name
                if kind == "node" and "content" in data:
                    data["content"] = message(data["content"])
            return result
        return value

    result = deepcopy(params)
    if action in {"upload_group_file", "upload_private_file"}:
        if isinstance(result.get("file"), str):
            result["file"] = replace(result["file"])
    for field in ("message", "messages"):
        if field in result:
            result[field] = message(result[field])
    return result
