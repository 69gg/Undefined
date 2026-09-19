"""文件准备错误与明确的 OneBot API 拒绝。"""

from typing import Any


class FileTransferError(RuntimeError):
    file_transfer_error = True

    def __init__(self, mode: str, message: str, *, stage: str = "prepare") -> None:
        self.mode = mode
        self.stage = stage
        self.user_message = f"本地文件传输失败（{mode}，{stage}）：{message}"
        super().__init__(self.user_message)


class OneBotAPIError(RuntimeError):
    """协议端明确返回失败；区别于断连、超时及文件准备失败。"""

    def __init__(self, message: str, retcode: Any) -> None:
        self.message = message
        self.retcode = retcode
        super().__init__(f"API 调用失败: {message} (retcode={retcode})")
