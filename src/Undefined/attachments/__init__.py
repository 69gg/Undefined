"""附件注册表与富媒体消息辅助工具包。

聚合 models、segments、registry、render 子模块的公开 API；
下游可 ``from Undefined.attachments import AttachmentRegistry`` 等。
"""

from Undefined.attachments.models import (
    AttachmentRecord,
    AttachmentRenderError,
    RegisteredMessageAttachments,
    RenderedRichMessage,
)
from Undefined.attachments.forward_snapshot import (
    load_forward_snapshot,
    save_forward_snapshot,
)
from Undefined.attachments.registry import AttachmentRegistry
from Undefined.attachments.render import (
    dispatch_pending_file_sends,
    render_message_with_attachments,
    render_message_with_pic_placeholders,
)
from Undefined.attachments.segments import (
    attachment_ref_to_tag,
    append_attachment_text,
    attachment_refs_to_text,
    attachment_refs_to_tags,
    attachment_refs_to_xml,
    build_attachment_scope,
    register_message_attachments,
    scope_from_context,
)

__all__ = [
    "AttachmentRecord",
    "AttachmentRegistry",
    "AttachmentRenderError",
    "RegisteredMessageAttachments",
    "RenderedRichMessage",
    "attachment_ref_to_tag",
    "append_attachment_text",
    "attachment_refs_to_text",
    "attachment_refs_to_tags",
    "attachment_refs_to_xml",
    "build_attachment_scope",
    "dispatch_pending_file_sends",
    "load_forward_snapshot",
    "register_message_attachments",
    "render_message_with_attachments",
    "render_message_with_pic_placeholders",
    "save_forward_snapshot",
    "scope_from_context",
]
