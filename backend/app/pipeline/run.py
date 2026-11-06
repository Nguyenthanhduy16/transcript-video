"""Chạy toàn bộ pipeline cho một job."""
from __future__ import annotations

import logging
import time
import shutil
from pathlib import Path

from . import asr, diarize, source
from .build import enrich_cue, finalize, normalize_cues, now_iso
from .cues import cues_from_asr, split_long_cue
from .subtitles import parse_subtitle_file
from .translate import LLMUnavailable, Translator
from .. import storage

log = logging.getLogger(__name__)

# (tên bước, % bắt đầu, % kết thúc)
STAGES = {
    "fetch": (0, 10), "asr": (10, 55), "segment": (55, 58), "diarize": (58, 65),
    "furigana": (65, 70), "translate": (70, 98), "save": (98, 100),
}


def run_pipeline(params: dict, report) -> dict:
    """params: url | upload_path, subtitle_path, title, series, episode, lang, target, glossary, force_asr.
    report(stage, frac, message) cập nhật tiến trình."""
    t_start = time.time()
    stats: dict = {}
    lang = params.get("lang") or "ja"
    target = params.get("target") or "vi"
    warnings: list[str] = []

    def step(stage, frac=0.0, msg=""):
        a, b = STAGES[stage]
        report(stage, a + (b - a) * frac, msg)

    # ---------------------------------------------------------------- 1. lấy nguồn
    step("fetch", 0, "Đang đọc nguồn video")
    url = (params.get("url") or "").strip()
    raw_cues: list[dict] | None = None
    wav: Path | None = None
    sub_kind = None
    duration = None
    title = params.get("title")

    if params.get("upload_path"):
        up = Path(params["upload_path"])
        video_id = params["video_id"]
        mdir = source.media_dir(video_id)
        player = {"type": "html5", "src": f"/media/{video_id}/{up.name}"}
        duration = source.probe_media(up, require_audio=not params.get("subtitle_path"))["duration"]
        src_info = {"kind": "upload", "filename": params.get("original_name", up.name)}
        title = title or Path(params.get("original_name", up.name)).stem
        media_src = up
    else:
        kind = source.kind_of(url)
        yt = source.youtube_id(url)
        video_id = params.get("video_id") or (yt if yt else source.make_video_id(url))
        mdir = source.media_dir(video_id)
        src_info = {"kind": kind, "url": url}
        media_src = None
        if kind == "media":
            player = {"type": "html5", "src": url}
            if url.split("?")[0].lower().endswith(".m3u8"):
                media_src = url                      # HLS: ffmpeg đọc trực tiếp từng đoạn
            else:
                step("fetch", 0.2, "Đang tải file video")
                media_src = source.download_media(url, mdir)
            duration = source.probe_media(media_src, require_audio=not params.get("subtitle_path"))["duration"]
            title = title or Path(url.split("?")[0]).stem
        else:
            info = source.fetch_info(url)
            title = title or info.get("title")
            duration = info.get("duration")
            if kind == "youtube":
                player = {"type": "youtube", "youtubeId": yt}
            else:
                step("fetch", 0.3, "Đang tải video từ trang nguồn")
                vpath = source.download_video(url, mdir)
                player = {"type": "html5", "src": f"/media/{video_id}/{vpath.name}"}
                media_src = vpath
            if not params.get("subtitle_path") and not params.get("force_asr"):
                picked = source.pick_subtitle(info, lang, allow_auto=params.get("allow_auto_subs", False))
                if picked:
                    step("fetch", 0.6, f"Tải phụ đề có sẵn ({picked[1]}: {picked[0]})")
                    sub_path = source.download_subtitle(url, picked[0], picked[1], mdir)
                    raw_cues = parse_subtitle_file(sub_path)
                    sub_kind = f"{kind}_{picked[1]}"

    if params.get("subtitle_path") and not params.get("force_asr"):
        raw_cues = parse_subtitle_file(params["subtitle_path"])
        sub_kind = "upload"

    # ---------------------------------------------------------------- 2. ASR (nếu không có phụ đề)
    if raw_cues is None:
        step("fetch", 0.8, "Đang tách audio (WAV 16 kHz mono)")
        if media_src is not None:
            wav = source.extract_audio(media_src, mdir / "audio.wav")
        else:
            wav = source.download_audio(url, mdir)
        duration = duration or source.probe_duration(wav)
        step("asr", 0, "Đang nhận dạng giọng nói (ASR)")
        t0 = time.time()
        res = asr.transcribe(str(wav), lang, progress=lambda f: step("asr", f, "Đang nhận dạng giọng nói"),
                             duration=duration)
        stats["asrSec"] = round(time.time() - t0, 2)
        stats["asrEngine"] = res.get("engine")
        step("segment", 0, "Đang chia câu")
        raw_cues = cues_from_asr(res["segments"])
        sub_kind = "asr"
    else:
        step("segment", 0, f"Đã có phụ đề gốc ({len(raw_cues)} dòng) – bỏ qua ASR")
        split = []
        for c in raw_cues:
            split.extend(split_long_cue(c))
        raw_cues = split

    cues = normalize_cues(raw_cues, lang)
    if not cues:
        from ..errors import PipelineError
        raise PipelineError("NO_SPEECH", "Không nhận được câu thoại nào: video không có tiếng nói hoặc phụ đề trống")

    # ---------------------------------------------------------------- 3. người nói
    need_spk = not any(c.get("speaker") for c in cues) and params.get("diarize", True)
    if need_spk and diarize.available():
        step("diarize", 0, "Đang nhận diện người nói")
        t0 = time.time()
        try:
            if wav is None and media_src is not None:
                wav = source.extract_audio(media_src, mdir / "audio.wav")
            if wav is not None:
                if diarize.mode() == "embedding":
                    n = diarize.assign_by_embedding(cues, asr.load_wav(str(wav)), params.get("num_speakers"))
                    stats["speakersFound"] = n
                else:
                    diarize.assign_from_turns(cues, diarize.diarize_pyannote(str(wav)))
        except Exception as e:   # không chặn pipeline
            warnings.append(f"Nhận diện người nói lỗi: {e}")
        stats["diarizeSec"] = round(time.time() - t0, 2)

    # ---------------------------------------------------------------- 4. furigana / tách từ
    step("furigana", 0, "Đang tách từ và sinh furigana")
    t0 = time.time()
    for c in cues:
        enrich_cue(c, lang)
    stats["nlpSec"] = round(time.time() - t0, 2)

    # ---------------------------------------------------------------- 5. dịch + phân tích
    step("translate", 0, "Đang dịch và phân tích (LLM)")
    try:
        tr = Translator(lang, target, params.get("glossary", ""))
        t0 = time.time()
        warnings += tr.process(cues, progress=lambda f: step("translate", f, "Đang dịch và phân tích (LLM)"))
        stats["llmSec"] = round(time.time() - t0, 2)
        stats["llmUsage"] = tr.usage_summary()
    except LLMUnavailable as e:
        warnings.append(f"Bỏ qua bước dịch/phân tích: LLM chưa sẵn sàng ({e}). "
                        "Đặt ANTHROPIC_API_KEY rồi bấm 'Dịch lại' trong trang chỉnh sửa.")

    # ---------------------------------------------------------------- 6. lưu
    step("save", 0, "Đang lưu")
    old = storage.load_transcript(video_id) or {}
    doc = {
        "videoId": video_id, "title": title or video_id,
        "series": params.get("series") or old.get("series") or "",
        "episode": params.get("episode") if params.get("episode") is not None else old.get("episode"),
        "lang": lang, "target": target, "duration": duration,
        "player": player, "source": {**src_info, "subtitle": sub_kind},
        "glossary": params.get("glossary", ""),
        "speakers": old.get("speakers", []),
        "createdAt": old.get("createdAt") or now_iso(),
        "warnings": warnings, "cues": cues,
        "stats": {**stats, "totalSec": round(time.time() - t_start, 2), "cueCount": len(cues)},
    }
    finalize(doc)
    storage.save_transcript(doc)
    if wav and wav.exists() and not params.get("keep_audio"):
        wav.unlink(missing_ok=True)
    step("save", 1, "Hoàn tất")
    return doc
