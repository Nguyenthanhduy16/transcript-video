"""Worker xử lý transcript: nhận job từ hàng đợi BullMQ (Redis) và chạy pipeline.

    REDIS_URL=redis://localhost:6379 python -m app.worker [--concurrency 1]

- Mỗi job chạy trong thread riêng (pipeline là code đồng bộ, tốn CPU) – event loop vẫn gia hạn khoá job.
- Tiến trình gửi qua job.updateProgress({stage, pct, message}).
- Lỗi được phân loại (app/errors.py): lỗi vĩnh viễn (link 404, file hỏng…) → thất bại ngay với lý do rõ;
  lỗi tạm thời (mạng, API quá tải) → BullMQ thử lại (attempts=2, backoff mũ).
- Một job lỗi không làm worker dừng; Ctrl+C / SIGTERM → đóng worker gọn gàng (job đang chạy được trả lại hàng đợi).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import time

from .errors import PipelineError, classify_exception

log = logging.getLogger("worker")


def _retranslate(params, report):
    from .main import _retranslate as fn   # tái dùng logic dịch lại của API
    try:
        return fn(params, report)
    except Exception as e:
        raise classify_exception(e) from e


def _transcript(params, report):
    from .pipeline.run import run_pipeline
    try:
        return run_pipeline(params, report)
    except Exception as e:  # chuẩn hoá lỗi để API/CMS hiển thị lý do rõ ràng
        raise classify_exception(e) from e


PROCESSORS = {"transcript": _transcript, "retranslate": _retranslate}


async def process(job, token=None):
    from bullmq import UnrecoverableError
    loop = asyncio.get_running_loop()
    fn = PROCESSORS.get(job.name)
    if not fn:
        raise UnrecoverableError(f"UNKNOWN_JOB: loại job không hỗ trợ '{job.name}'")
    last = [0.0]

    def report(stage, pct, msg=""):
        now = time.time()
        if now - last[0] < 1 and pct < 100:      # tối đa 1 lần/giây
            return
        last[0] = now
        asyncio.run_coroutine_threadsafe(job.updateProgress({"stage": stage, "pct": round(pct, 1), "message": msg}), loop)

    t0 = time.time()
    try:
        doc = await asyncio.to_thread(fn, dict(job.data), report)
    except PipelineError as e:
        log.warning("job %s lỗi %s", job.id, e)
        if e.retryable:
            raise Exception(str(e))
        raise UnrecoverableError(str(e))
    except Exception as e:
        pe = classify_exception(e)
        log.exception("job %s lỗi", job.id)
        raise (Exception if pe.retryable else UnrecoverableError)(str(pe))
    log.info("job %s xong trong %.1fs: %s", job.id, time.time() - t0, doc.get("videoId"))
    return {"videoId": doc["videoId"], "warnings": doc.get("warnings", []), "stats": doc.get("stats", {})}


async def main(concurrency: int):
    from bullmq import Worker
    from .queue import QUEUE_NAME, REDIS_URL
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    worker = Worker(QUEUE_NAME, process, {"connection": REDIS_URL, "concurrency": concurrency,
                                          "lockDuration": 120_000, "autorun": True})
    log.info("Worker sẵn sàng: hàng đợi '%s' @ %s, concurrency=%d", QUEUE_NAME, REDIS_URL, concurrency)
    await stop.wait()
    log.info("Đang dừng worker…")
    await worker.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=1)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main(a.concurrency))
