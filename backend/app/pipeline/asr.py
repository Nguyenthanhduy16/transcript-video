"""Nhận dạng giọng nói: faster-whisper (mặc định) hoặc WhisperX (căn thời gian từng từ chính xác hơn).

Cả hai là phụ thuộc tuỳ chọn – cài khi có GPU:
    pip install faster-whisper        # hoặc: pip install whisperx
"""
from __future__ import annotations

import re
from typing import Callable

from ..config import ASR_COMPUTE_TYPE, ASR_DEVICE, ASR_ENGINE, ASR_MODEL

# Whisper hay "bịa" các câu này ở đoạn im lặng / nhạc nền
HALLUCINATIONS = re.compile(
    r"(ご視聴ありがとうございました|チャンネル登録|字幕|お疲れ様でした。?$|最後までご覧いただき)")


class ASRUnavailable(RuntimeError):
    pass


_model_cache: dict = {}


def transcribe(wav_path: str, lang: str, progress: Callable[[float], None] | None = None,
               duration: float | None = None) -> dict:
    """Trả về {"words": [{start,end,word}], "segments": [{start,end,text}]}."""
    if ASR_ENGINE == "whisperx":
        return _whisperx(wav_path, lang)
    return _faster_whisper(wav_path, lang, progress, duration)


def _faster_whisper(wav_path, lang, progress, duration):
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise ASRUnavailable(
            "Video chưa có phụ đề nên cần ASR, nhưng chưa cài faster-whisper. "
            "Chạy: pip install faster-whisper (khuyến nghị có GPU), hoặc tải lên file phụ đề .srt/.vtt.") from e
    key = ("fw", ASR_MODEL, ASR_DEVICE)
    if key not in _model_cache:
        _model_cache[key] = WhisperModel(ASR_MODEL, device=ASR_DEVICE, compute_type=ASR_COMPUTE_TYPE)
    model = _model_cache[key]
    segments, info = model.transcribe(
        wav_path, language=lang, vad_filter=True, word_timestamps=True,
        condition_on_previous_text=False,   # giảm lặp/bịa câu
        vad_parameters={"min_silence_duration_ms": 400},
    )
    total = duration or getattr(info, "duration", None) or 0
    words, segs = [], []
    for s in segments:
        if s.no_speech_prob > 0.6 or HALLUCINATIONS.search(s.text):
            continue
        segs.append({"start": s.start, "end": s.end, "text": s.text.strip()})
        for w in s.words or []:
            words.append({"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()})
        if progress and total:
            progress(min(1.0, s.end / total))
    return {"words": words, "segments": segs}


def _whisperx(wav_path, lang):
    try:
        import whisperx
    except ImportError as e:
        raise ASRUnavailable("Chưa cài whisperx (pip install whisperx)") from e
    device = "cuda" if ASR_DEVICE in ("auto", "cuda") else "cpu"
    try:
        import torch
        if not torch.cuda.is_available():
            device = "cpu"
    except ImportError:
        device = "cpu"
    ctype = "float16" if device == "cuda" else "int8"
    model = whisperx.load_model(ASR_MODEL, device, compute_type=ctype, language=lang)
    audio = whisperx.load_audio(wav_path)
    result = model.transcribe(audio, batch_size=16, language=lang)
    align_model, meta = whisperx.load_align_model(language_code=lang, device=device)
    aligned = whisperx.align(result["segments"], align_model, meta, audio, device)
    words, segs = [], []
    for s in aligned["segments"]:
        if HALLUCINATIONS.search(s.get("text", "")):
            continue
        segs.append({"start": s["start"], "end": s["end"], "text": s["text"].strip()})
        for w in s.get("words", []):
            if "start" in w:
                words.append({"start": round(w["start"], 3), "end": round(w["end"], 3), "word": w["word"].strip()})
    return {"words": words, "segments": segs}
