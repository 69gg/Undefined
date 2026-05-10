"""B 站下载相关异常。"""

from __future__ import annotations


class BilibiliError(Exception):
    """B 站模块基础异常。"""


class ApiResponseError(BilibiliError):
    """B 站 API 返回失败或格式异常。"""


class DownloadError(BilibiliError):
    """视频流下载或合并失败。"""


class FFmpegError(DownloadError):
    """ffmpeg 合并失败。"""


class FFmpegNotFoundError(FFmpegError):
    """找不到 ffmpeg 可执行文件。"""
