"""Hàng đợi job nền đơn giản (thread pool, trạng thái lưu file JSON).

Production: thay bằng Celery/RQ/BullMQ – giao diện submit()/get() giữ nguyên.
"""
from __future__ import annotations

import json
import logging
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from .config import JOBS_DIR
from .pipeline.build import now_iso

log = logging.getLogger(__name__)


class JobManager:
    def __init__(self, workers: int = 1):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}
        for p in JOBS_DIR.glob("*.json"):
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if j["status"] in ("queued", "running"):   # server khởi động lại giữa chừng
                j.update(status="error", error="Server khởi động lại khi job đang chạy")
            self.jobs[j["id"]] = j

    def _save(self, job: dict) -> None:
        (JOBS_DIR / f"{job['id']}.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")

    def _update(self, jid: str, **kw) -> None:
        with self.lock:
            job = self.jobs[jid]
            job.update(kw, updatedAt=now_iso())
            self._save(job)

    def submit(self, fn, params: dict, label: str) -> dict:
        jid = uuid.uuid4().hex[:12]
        job = {"id": jid, "label": label, "status": "queued", "stage": "queued", "progress": 0,
               "message": "Đang chờ", "videoId": params.get("video_id"), "error": None,
               "warnings": [], "createdAt": now_iso(), "updatedAt": now_iso(),
               "params": {k: v for k, v in params.items() if k in ("url", "title", "series", "episode", "lang", "target")}}
        with self.lock:
            self.jobs[jid] = job
            self._save(job)
        self.pool.submit(self._run, jid, fn, params)
        return job

    def _run(self, jid, fn, params):
        self._update(jid, status="running", message="Bắt đầu")

        def report(stage, pct, msg=""):
            self._update(jid, stage=stage, progress=round(pct, 1), message=msg)
        try:
            doc = fn(params, report)
            self._update(jid, status="done", progress=100, stage="done", message="Hoàn tất",
                         videoId=doc["videoId"], warnings=doc.get("warnings", []))
        except Exception as e:
            log.error("Job %s lỗi: %s", jid, traceback.format_exc())
            self._update(jid, status="error", error=str(e), message="Lỗi")

    def get(self, jid: str) -> dict | None:
        return self.jobs.get(jid)

    def list(self) -> list[dict]:
        return sorted(self.jobs.values(), key=lambda j: j["createdAt"], reverse=True)
