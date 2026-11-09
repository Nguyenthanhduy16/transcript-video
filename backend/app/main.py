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
from .queue import QUEUE_BACKEND, get_queue
from .pipeline import source
from .pipeline.build import enrich_cue, finalize, normalize_cues
from .pipeline.cues import classify
from .pipeline.translate import LLMUnavailable, Translator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = FastAPI(title="Video Transcript học ngoại ngữ")
# Extension Chrome (và web app chạy ở cổng khác) gọi API trực tiếp
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
app.add_middleware(CORSMiddleware, allow_origin_regex=r"^(chrome-extension://.*|http://(localhost|127\.0\.0\.1)(:\d+)?)$",
                   allow_methods=["*"], allow_headers=["*"])
jobs = get_queue()


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
    num_speakers: int | None = None


@app.post("/api/jobs")
def create_job(body: JobIn):
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(400, "Link phải bắt đầu bằng http:// hoặc https://")
    params = body.model_dump()
    yt = source.youtube_id(body.url)
    params["video_id"] = yt or source.make_video_id(body.url)
    return jobs.submit("transcript", params, label=body.title or body.url)


@app.post("/api/jobs/upload")
async def create_upload_job(
    video: UploadFile = File(...), subtitle: UploadFile | None = File(None),
    title: str = Form(""), series: str = Form(""), episode: int | None = Form(None),
    lang: str = Form("ja"), target: str = Form("vi"), glossary: str = Form(""),
    force_asr: bool = Form(False), num_speakers: int | None = Form(None),
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
              "lang": lang, "target": target, "glossary": glossary, "force_asr": force_asr,
              "num_speakers": num_speakers}
    if subtitle and subtitle.filename:
        sext = Path(subtitle.filename).suffix.lower()
        if sext not in (".srt", ".vtt", ".ass", ".ssa"):
            raise HTTPException(400, "Phụ đề phải là .srt/.vtt/.ass")
        spath = mdir / f"original{sext}"
        with spath.open("wb") as f:
            shutil.copyfileobj(subtitle.file, f)
        params["subtitle_path"] = str(spath)
    return jobs.submit("transcript", params, label=title or video.filename)


def _video_id_for(url: str) -> str:
    yt = source.youtube_id(url)
    return yt or source.make_video_id(url)


@app.get("/api/resolve")
def resolve(url: str):
    """Extension hỏi: video ở link này đã có transcript chưa? Trả về videoId tương ứng.
    Khớp theo: id YouTube / mã băm của link / link nguồn hoặc file phát đã lưu trong transcript."""
    from urllib.parse import urlparse
    vid = _video_id_for(url)
    doc = None
    try:
        doc = storage.load_transcript(vid)
    except ValueError:
        pass
    if not doc:
        path = urlparse(url).path
        for v in storage.list_transcripts():
            pl = v.get("player") or {}
            if pl.get("src") and (pl["src"] == url or (pl["src"].startswith("/") and path == pl["src"])):
                vid, doc = v["videoId"], v
                break
    kind = "youtube" if source.youtube_id(url) else "media"
    return {"videoId": vid, "exists": bool(doc), "kind": kind,
            "title": doc.get("title") if doc else None, "cueCount": (doc or {}).get("cueCount") or len((doc or {}).get("cues", []))}


class SubtitleJobIn(BaseModel):
    url: str                    # link trang video (YouTube…)
    subtitle: str               # nội dung WebVTT/SRT đọc từ trang
    format: str = "vtt"
    subtitle_kind: str = "youtube_manual"   # youtube_manual | youtube_auto | page
    title: str | None = None
    duration: float | None = None
    lang: str = "ja"
    target: str = "vi"
    glossary: str = ""


@app.post("/api/jobs/subtitle")
def create_subtitle_job(body: SubtitleJobIn):
    """Extension gửi phụ đề gốc đọc được trên trang → tách từ, furigana, dịch; không tải video."""
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(400, "Link phải bắt đầu bằng http:// hoặc https://")
    if body.format not in ("vtt", "srt"):
        raise HTTPException(400, "format: vtt | srt")
    if not body.subtitle.strip() or len(body.subtitle) > 5_000_000:
        raise HTTPException(400, "Phụ đề trống hoặc quá lớn")
    vid = _video_id_for(body.url)
    mdir = source.media_dir(vid)
    sp = mdir / f"page_subtitle.{body.format}"
    sp.write_text(body.subtitle, encoding="utf-8")
    params = {"url": body.url, "video_id": vid, "subtitle_path": str(sp), "subtitle_kind": body.subtitle_kind,
              "title": body.title, "duration": body.duration, "lang": body.lang, "target": body.target,
              "glossary": body.glossary}
    return jobs.submit("transcript", params, label=body.title or body.url)


class TranslateIn(BaseModel):
    text: str
    target: str = "vi"
    source: str = "auto"


@app.post("/api/translate")
def translate_selection(body: TranslateIn):
    """Dịch đoạn văn người dùng bôi đen (extension). 503 khi server chưa có API key Claude."""
    from .pipeline import quick_translate
    try:
        return quick_translate.translate(body.text, body.target, body.source)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LLMUnavailable as e:
        raise HTTPException(503, f"LLM_UNAVAILABLE: server chưa có API key Claude ({e})")
    except Exception as e:
        raise HTTPException(502, f"Dịch lỗi: {e}")


POS_VI = {"noun": "danh từ", "pronoun": "đại từ", "verb": "động từ", "i-adjective": "tính từ đuôi い",
          "na-adjective": "tính từ đuôi な", "adverb": "phó từ", "interjection": "thán từ", "conjunction": "liên từ",
          "adnominal": "liên thể từ", "particle": "trợ từ", "auxiliary": "trợ động từ"}


class AnalyzeIn(BaseModel):
    text: str


@app.post("/api/analyze-ja")
def analyze_japanese(body: AnalyzeIn):
    """Tách từ tiếng Nhật cho đoạn bôi đen (không cần LLM): furigana, cách đọc, romaji, dạng từ điển, kanji (Hán Việt)."""
    from .pipeline import japanese, kanji as kanjidic
    text = body.text.strip()
    if not text or len(text) > 2000:
        raise HTTPException(400, "Đoạn văn trống hoặc dài hơn 2.000 ký tự")
    toks = japanese.tokenize(text)
    words = [t for t in toks if t["isWord"]]
    return {
        "tokens": toks,
        "reading": "".join(t["reading"] or t["surface"] for t in toks if t["pos"] not in ("space", "speaker")),
        "romaji": japanese.romaji_line(toks),
        "lemma": words[0]["lemma"] if len(words) == 1 else None,
        "lemmaReading": words[0]["lemmaReading"] if len(words) == 1 else None,
        "pos": POS_VI.get(words[0]["pos"], words[0]["posJa"]) if len(words) == 1 else None,
        "kanji": kanjidic.lookup_many(japanese.extract_kanji(text)[:20]),
    }


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
    if not doc:
        from .errors import PipelineError
        raise PipelineError("NOT_FOUND", f"Không có transcript cho video '{params['video_id']}'")
    ids = set(params["ids"]) if params.get("ids") else None
    report("translate", 5, "Đang dịch lại")
    for c in doc["cues"]:
        if ids is None or c["id"] in ids:
            c.pop("vocab", None), c.pop("kanji", None)
            enrich_cue(c, doc["lang"])
    try:
        tr = Translator(doc["lang"], doc["target"], doc.get("glossary", ""))
    except LLMUnavailable as e:
        from .errors import PipelineError
        raise PipelineError("LLM_UNAVAILABLE", f"LLM chưa sẵn sàng: {e}")
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
    return jobs.submit("retranslate", {"video_id": video_id, "ids": ids}, label=f"Dịch lại {doc['title']}")


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
    from .pipeline import asr, diarize
    try:
        counts = jobs.counts()
    except Exception as e:      # Redis không kết nối được
        counts = {"error": str(e)}
    return {"ok": True, "queue": QUEUE_BACKEND, "jobs": counts,
            "asr": asr.available("ja"), "asrEngine": asr.resolve_engine("ja"),
            "diarization": diarize.mode(), "ffmpeg": bool(shutil.which("ffmpeg")),
            "llm": bool(u.find_spec("anthropic"))}


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
