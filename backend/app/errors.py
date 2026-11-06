"""Lỗi pipeline có mã + lý do tiếng Việt, để worker trả về trạng thái rõ ràng.

retryable=True: lỗi tạm thời (mạng, API quá tải) → hàng đợi được phép thử lại.
"""
from __future__ import annotations


class PipelineError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable


def classify_exception(e: Exception) -> PipelineError:
    """Chuyển lỗi bất kỳ thành PipelineError có mã."""
    if isinstance(e, PipelineError):
        return e
    from .pipeline.asr import ASRUnavailable
    from .pipeline.source import SourceError
    msg = str(e)
    if isinstance(e, ASRUnavailable):
        return PipelineError("ASR_UNAVAILABLE", msg)
    if isinstance(e, SourceError):
        return PipelineError(e.code, msg, retryable=e.retryable)
    if isinstance(e, MemoryError):
        return PipelineError("OUT_OF_MEMORY", "Hết bộ nhớ khi xử lý – thử video ngắn hơn hoặc tăng RAM worker", True)
    if isinstance(e, (ConnectionError, TimeoutError)):
        return PipelineError("NETWORK", msg or "Lỗi mạng", retryable=True)
    return PipelineError("INTERNAL", f"Lỗi không xác định: {type(e).__name__}: {msg}")
