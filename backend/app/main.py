"""API + phục vụ frontend tĩnh.

Chạy:  uvicorn app.main:app --reload --port 8000   (trong thư mục backend/)
"""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import storage
from .config import FRONTEND_DIR, MEDIA_DIR
from .jobs import JobManager
from .pipeline import source
from .pipeline.build import enrich_cue, finalize, normalize_cues
from .pipeline.cues import classify
from .pipeline.run import run_pipeline
from .pipeline.translate import LLMUnavailable, Translator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = FastAPI(title="Video Transcript học ngoại ngữ")
jobs = JobManager(workers=1)


# ------------------------------------------------------------------ jobs
class JobIn(BaseModel):
    url: str
    title: str | None = None
    series: str | None = None
    episode: int | None = None
    lang: str = "ja"
    target: str = "vi"
    glossary: str = ""
    force_asr: bool = False
    allow_auto_subs: bool = False


@app.post("/api/jobs")
def create_job(body: JobIn):
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(400, "Link phải bắt đầu bằng http:// hoặc https://")
    params = body.model_dump()
    yt = source.youtube_id(body.url)
    params["video_id"] = yt or source.make_video_id(body.url)
    return jobs.submit(run_pipeline, params, label=body.title or body.url)


@app.post("/api/jobs/upload")
async def create_upload_job(
    video: UploadFile = File(...), subtitle: UploadFile | None = File(None),
    title: str = Form(""), series: str = Form(""), episode: int | None = Form(None),
    lang: str = Form("ja"), target: str = Form("vi"), glossary: str = Form(""),
    force_asr: bool = Form(False),
):
    ext = Path(video.filename or "video.mp4").suffix.lower() or ".mp4"
    if ext not in source.MEDIA_EXT:
        raise HTTPException(400, f"Định dạng {ext} chưa hỗ trợ")
    video_id = "u" + uuid.uuid4().hex[:10]
    mdir = source.media_dir(video_id)
    vpath = mdir / f"video{ext}"
    with vpath.open("wb") as f:
        shutil.copyfileobj(video.file, f)
    params = {"video_id": video_id, "upload_path": str(vpath), "original_name": video.filename,
              "title": title or None, "series": series or None, "episode": episode,
              "lang": lang, "target": target, "glossary": glossary, "force_asr": force_asr}
    if subtitle and subtitle.filename:
        sext = Path(subtitle.filename).suffix.lower()
        if sext not in (".srt", ".vtt", ".ass", ".ssa"):
            raise HTTPException(400, "Phụ đề phải là .srt/.vtt/.ass")
        spath = mdir / f"original{sext}"
        with spath.open("wb") as f:
            shutil.copyfileobj(subtitle.file, f)
        params["subtitle_path"] = str(spath)
    return jobs.submit(run_pipeline, params, label=title or video.filename)


@app.get("/api/jobs")
def list_jobs():
    return jobs.list()


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "Không tìm thấy job")
    return j


# ------------------------------------------------------------------ transcripts
def _load(video_id: str) -> dict:
    try:
        doc = storage.load_transcript(video_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not doc:
        raise HTTPException(404, "Chưa có transcript cho video này")
    return doc


@app.get("/api/videos")
def list_videos():
    return storage.list_transcripts()


@app.get("/api/videos/{video_id}")
def get_video(video_id: str):
    return _load(video_id)


@app.get("/api/series/{series}/episodes")
def series_episodes(series: str):
    eps = [v for v in storage.list_transcripts() if v.get("series") == series]
    return sorted(eps, key=lambda v: (v.get("episode") is None, v.get("episode") or 0, v.get("title") or ""))


class CueEdit(BaseModel):
    id: int | None = None
    start: float
    end: float
    speaker: str | None = None
    type: str | None = None
    text: str
    translation: str = ""


class SpeakerEdit(BaseModel):
    name: str
    display: str
    color: str


class VideoEdit(BaseModel):
    title: str | None = None
    series: str | None = None
    episode: int | None = None
    glossary: str | None = None
    speakers: list[SpeakerEdit] | None = None
    cues: list[CueEdit] | None = None


@app.put("/api/videos/{video_id}")
def edit_video(video_id: str, body: VideoEdit):
    """Sửa transcript thủ công. Cue đổi nội dung được tách từ lại; phân tích cũ bị xoá
    (bấm 'Dịch lại' để LLM phân tích lại các cue đó)."""
    doc = _load(video_id)
    for k in ("title", "series", "episode", "glossary"):
        v = getattr(body, k)
        if v is not None:
            doc[k] = v
    if body.speakers is not None:
        doc["speakers"] = [s.model_dump() for s in body.speakers]
    changed: list[int] = []
    if body.cues is not None:
        old = {c["id"]: c for c in doc["cues"]}
        next_id = max(old, default=0) + 1
        new_cues = []
        for e in body.cues:
            if e.end <= e.start:
                raise HTTPException(400, f"Cue {e.id}: end phải lớn hơn start")
            prev = old.get(e.id) if e.id is not None else None
            ctype = e.type or classify(e.text)
            if prev and prev["text"] == e.text and prev["type"] == ctype:
                c = {**prev, "start": e.start, "end": e.end, "speaker": e.speaker, "translation": e.translation}
            else:
                c = {"id": e.id if prev else next_id, "start": e.start, "end": e.end, "speaker": e.speaker,
                     "type": ctype, "text": e.text.strip(), "translation": e.translation,
                     "multiSpeaker": bool(prev and prev.get("multiSpeaker"))}
                if not prev:
                    next_id += 1
                enrich_cue(c, doc["lang"])
                changed.append(c["id"])
            new_cues.append(c)
        new_cues.sort(key=lambda c: c["start"])
        doc["cues"] = new_cues
    finalize(doc)
    doc["needsAnalysis"] = sorted(set(doc.get("needsAnalysis", [])) | set(changed))
    storage.save_transcript(doc)
    return doc


class RetranslateIn(BaseModel):
    ids: list[int] | None = None   # None = cue đã sửa (needsAnalysis) hoặc toàn bộ nếu all=True
    all: bool = False


def _retranslate(params, report):
    doc = storage.load_transcript(params["video_id"])
    ids = set(params["ids"]) if params.get("ids") else None
    report("translate", 5, "Đang dịch lại")
    for c in doc["cues"]:
        if ids is None or c["id"] in ids:
            c.pop("vocab", None), c.pop("kanji", None)
            enrich_cue(c, doc["lang"])
    try:
        tr = Translator(doc["lang"], doc["target"], doc.get("glossary", ""))
    except LLMUnavailable as e:
        raise RuntimeError(f"LLM chưa sẵn sàng: {e}")
    warns = tr.process(doc["cues"], only_ids=ids, progress=lambda f: report("translate", 5 + 90 * f, "Đang dịch lại"))
    for c in doc["cues"]:
        c.pop("_cand", None), c.pop("_kanji", None)
    doc["needsAnalysis"] = [] if ids is None else [i for i in doc.get("needsAnalysis", []) if i not in ids]
    doc["warnings"] = warns
    finalize(doc)
    storage.save_transcript(doc)
    return doc


@app.post("/api/videos/{video_id}/retranslate")
def retranslate(video_id: str, body: RetranslateIn):
    doc = _load(video_id)
    ids = body.ids if body.ids else (None if body.all else doc.get("needsAnalysis") or None)
    if ids is None and not body.all:
        raise HTTPException(400, "Không có cue nào cần dịch lại (truyền ids hoặc all=true)")
    return jobs.submit(_retranslate, {"video_id": video_id, "ids": ids}, label=f"Dịch lại {doc['title']}")


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: str):
    _load(video_id)
    storage.delete_transcript(video_id)
    shutil.rmtree(MEDIA_DIR / video_id, ignore_errors=True)
    return {"ok": True}


def _ts(sec: float, sep: str) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


@app.get("/api/videos/{video_id}/export.{fmt}")
def export(video_id: str, fmt: str, lang: str = "both"):
    if fmt not in ("srt", "vtt", "json"):
        raise HTTPException(400, "fmt: srt | vtt | json")
    doc = _load(video_id)
    if fmt == "json":
        return doc
    lines = ["WEBVTT", ""] if fmt == "vtt" else []
    sep = "." if fmt == "vtt" else ","
    for i, c in enumerate(doc["cues"], 1):
        src = (f"（{c['speaker']}）" if c.get("speaker") and not c.get("multiSpeaker") else "") + c["text"]
        parts = {"src": [src], "target": [c.get("translation") or ""], "both": [src, c.get("translation") or ""]}[
            "src" if lang == doc["lang"] else "target" if lang == doc["target"] else "both"]
        lines += [str(i), f"{_ts(c['start'], sep)} --> {_ts(c['end'], sep)}", *[p for p in parts if p], ""]
    return PlainTextResponse("\n".join(lines), media_type="text/plain; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{video_id}.{fmt}"'})


@app.get("/api/health")
def health():
    import importlib.util as u
    return {"ok": True, "asr": bool(u.find_spec("faster_whisper") or u.find_spec("whisperx")),
            "diarization": bool(u.find_spec("pyannote")), "ffmpeg": bool(shutil.which("ffmpeg"))}


# ------------------------------------------------------------------ static
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/watch")
def watch_page():
    return FileResponse(FRONTEND_DIR / "watch.html")


@app.get("/edit")
def edit_page():
    return FileResponse(FRONTEND_DIR / "edit.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
