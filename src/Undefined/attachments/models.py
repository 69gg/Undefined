"""附件领域模型与渲染异常类型。

定义 ``AttachmentRecord`` 等不可变数据类及 ``AttachmentRenderError``；
不含注册、解析或 CQ 渲染逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AttachmentRecord:
    """单条附件的持久化记录。

    由 ``AttachmentRegistry`` 写入磁盘并在消息渲染时按 UID 解析；
    ``prompt_ref()`` 供 LLM 上下文引用本地可用或远程 URL 附件。
    """

    uid: str
    scope_key: str
    kind: str
    media_type: str
    display_name: str
    source_kind: str
    source_ref: str
    local_path: str | None
    mime_type: str
    sha256: str
    created_at: str
    segment_data: dict[str, str]
    semantic_kind: str = ""
    description: str = ""

    def prompt_ref(self) -> dict[str, str]:
        """构建供提示词/历史引用的精简附件字典。

        Returns:
            含 ``uid``、``kind``、``media_type`` 等字段的字典；
            本地文件不可用时回退 ``source_ref``。
        """
        local_available = False
        if self.local_path is not None:
            try:
                local_available = Path(self.local_path).is_file()
            except OSError:
                local_available = False
        ref: dict[str, str] = {
            "uid": self.uid,
            "kind": self.kind,
            "media_type": self.media_type,
            "display_name": self.display_name,
        }
        if self.source_kind.strip():
            ref["source_kind"] = self.source_kind.strip()
        # 本地文件缺失时回退 source_ref，供 LLM 引用远程 URL
        if not local_available and self.source_ref.strip():
            ref["source_ref"] = self.source_ref.strip()
        if self.semantic_kind.strip():
            ref["semantic_kind"] = self.semantic_kind.strip()
        if self.description.strip():
            ref["description"] = self.description.strip()
        return ref


@dataclass(frozen=True)
class RegisteredMessageAttachments:
    """OneBot 消息段注册附件后的归一化结果。"""

    attachments: list[dict[str, str]]
    normalized_text: str
    forward_refs: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class RenderedRichMessage:
    """富媒体标签渲染后的投递与历史文本。"""

    delivery_text: str
    history_text: str
    attachments: list[dict[str, str]]
    pending_file_sends: tuple[AttachmentRecord, ...] = ()


class AttachmentRenderError(RuntimeError):
    """附件标签无法渲染时抛出（``strict=True`` 场景）。"""


class _RemoteAttachmentTooLarge(Exception):
    """远程下载超过字节上限时由 registry 内部捕获。"""

    def __init__(self, mime_type: str = "") -> None:
        self.mime_type = mime_type
