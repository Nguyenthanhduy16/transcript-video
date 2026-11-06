"""Hàng đợi job transcript – hai chế độ, cùng một giao diện submit()/get()/list():

- local (mặc định khi dev): thread trong chính process API (app/jobs.py).
- redis: BullMQ trên Redis. API chỉ đẩy job; worker riêng (`python -m app.worker`) nhận và xử lý.
  Backend NestJS của nhóm dùng BullMQ (Node) đọc/ghi cùng hàng đợi "transcript".

Hợp đồng dữ liệu của job (dùng chung với Người 3):
  name      : "transcript" | "retranslate"
  data      : {url | upload_path, subtitle_path?, video_id, title?, series?, episode?, lang, target,
               glossary?, force_asr?, num_speakers?}
  progress  : {stage, pct, message}                       (job.updateProgress)
  returnvalue (thành công): {videoId, warnings[], stats{}}
  failedReason (thất bại):  "MÃ_LỖI: lý do tiếng Việt"     (vd. "SOURCE_ERROR: Không tải được link (HTTP 404…)")
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid

from .pipeline.build import now_iso

QUEUE_BACKEND = os.getenv("QUEUE_BACKEND", "local")      # local | redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
QUEUE_NAME = os.getenv("QUEUE_NAME", "transcript")


def _public_params(p: dict) -> dict:
    return {k: v for k, v in p.items() if k in ("url", "title", "series", "episode", "lang", "target")}


class RedisQueue:
    """Đẩy/đọc job BullMQ. Chạy event loop riêng trong một thread để gọi từ code đồng bộ (FastAPI sync)."""

    def __init__(self, url: str = REDIS_URL, name: str = QUEUE_NAME):
        from bullmq import Queue
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True, name="bullmq-loop").start()
        self.queue = self._run(self._make(Queue, name, url))
        self.labels: dict[str, str] = {}

    async def _make(self, Queue, name, url):
        return Queue(name, {"connection": url})

    def _run(self, coro, timeout=15):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def submit(self, kind: str, params: dict, label: str) -> dict:
        jid = uuid.uuid4().hex[:12]
        data = {**params, "_label": label, "_createdAt": now_iso()}
        opts = {"jobId": jid, "attempts": 2, "backoff": {"type": "exponential", "delay": 10000},
                "removeOnComplete": {"count": 1000}, "removeOnFail": {"count": 1000}}
        self._run(self.queue.add(kind, data, opts))
        return self.get(jid) or {"id": jid, "status": "queued"}

    def get(self, jid: str) -> dict | None:
        return self._run(self._get(jid))

    async def _get(self, jid: str) -> dict | None:
        from bullmq import Job
        job = await Job.fromId(self.queue, jid)
        if not job:
            return None
        state = await job.getState()
        return _to_api(job, state)

    def list(self, limit: int = 30) -> list[dict]:
        return self._run(self._list(limit))

    async def _list(self, limit):
        jobs = await self.queue.getJobs(["active", "waiting", "delayed", "completed", "failed"], 0, limit)
        out = []
        for j in jobs:
            if j:
                out.append(_to_api(j, await j.getState()))
        return sorted(out, key=lambda x: x["createdAt"], reverse=True)

    def counts(self) -> dict:
        return self._run(self.queue.getJobCounts("waiting", "active", "completed", "failed", "delayed"))


def _to_api(job, state: str) -> dict:
    """Job BullMQ → định dạng job mà frontend/API đang dùng."""
    status = {"waiting": "queued", "delayed": "queued", "prioritized": "queued", "active": "running",
              "completed": "done", "failed": "error"}.get(state, state)
    prog = job.progress if isinstance(job.progress, dict) else {}
    rv = job.returnvalue if isinstance(job.returnvalue, dict) else {}
    data = job.data or {}
    created = data.get("_createdAt") or time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime((job.timestamp or 0) / 1000))
    return {
        "id": job.id, "kind": job.name, "label": data.get("_label") or data.get("url") or job.name,
        "status": status, "stage": "done" if status == "done" else prog.get("stage", "queued"),
        "progress": 100 if status == "done" else prog.get("pct", 0),
        "message": "Hoàn tất" if status == "done" else ("Lỗi" if status == "error" else prog.get("message", "Đang chờ")),
        "videoId": rv.get("videoId") or data.get("video_id"),
        "error": job.failedReason if status == "error" else None,
        "attempts": job.attemptsMade, "warnings": rv.get("warnings", []), "stats": rv.get("stats"),
        "createdAt": created, "updatedAt": now_iso(), "params": _public_params(data),
    }


_backend = None


def get_queue():
    """Singleton theo QUEUE_BACKEND."""
    global _backend
    if _backend is None:
        if QUEUE_BACKEND == "redis":
            _backend = RedisQueue()
        else:
            from .jobs import JobManager
            _backend = LocalAdapter(JobManager(workers=1))
    return _backend


class LocalAdapter:
    def __init__(self, mgr):
        self.mgr = mgr

    def submit(self, kind: str, params: dict, label: str) -> dict:
        from .worker import PROCESSORS
        return self.mgr.submit(PROCESSORS[kind], params, label)

    def get(self, jid):
        return self.mgr.get(jid)

    def list(self, limit: int = 30):
        return self.mgr.list()[:limit]

    def counts(self):
        js = self.mgr.list()
        return {s: sum(1 for j in js if j["status"] == s) for s in ("queued", "running", "done", "error")}
