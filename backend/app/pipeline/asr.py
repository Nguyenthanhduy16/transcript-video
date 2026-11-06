"""Nhận dạng giọng nói.

Engine:
- reazon        : sherpa-onnx + ReazonSpeech zipformer (tiếng Nhật, chạy CPU, có mốc thời gian từng token)
- whisper-onnx  : sherpa-onnx + Whisper small int8 (đa ngôn ngữ, CPU, chậm hơn ~10 lần, mốc theo VAD)
- faster-whisper / whisperx : khi có GPU (pip install faster-whisper | whisperx)
ASR_ENGINE=auto chọn reazon cho tiếng Nhật nếu đã chạy scripts/download_models.sh.

Mọi engine trả về {"segments": [{start, end, text, words:[{start,end,word}]}], "engine": ...}.
Với reazon/whisper-onnx, Silero VAD cắt audio thành từng lượt nói trước khi nhận dạng,
nên mốc đầu/cuối câu bám theo ranh giới tiếng nói thật.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from ..config import ASR_COMPUTE_TYPE, ASR_DENOISE, ASR_DEVICE, ASR_ENGINE, ASR_MODEL, ASR_THREADS, MODELS_DIR

SR = 16000
# Whisper hay "bịa" các câu này ở đoạn im lặng / nhạc nền
HALLUCINATIONS = re.compile(
    r"(ご視聴ありがとうございました|チャンネル登録|字幕|お疲れ様でした。?$|最後までご覧いただき)")

REAZON_DIR = MODELS_DIR / "sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01"
WHISPER_ONNX_DIR = MODELS_DIR / "sherpa-onnx-whisper-small"
VAD_MODEL = MODELS_DIR / "silero_vad.onnx"
DENOISE_MODEL = MODELS_DIR / "gtcrn_simple.onnx"
import os as _os
VAD_THRESHOLD = float(_os.getenv("VAD_THRESHOLD", "0.5"))
VAD_MIN_SILENCE = float(_os.getenv("VAD_MIN_SILENCE", "0.25"))


class ASRUnavailable(RuntimeError):
    pass


_cache: dict = {}
_lock = threading.Lock()


def resolve_engine(lang: str) -> str:
    if ASR_ENGINE != "auto":
        return ASR_ENGINE
    if lang == "ja" and (REAZON_DIR / "tokens.txt").exists() and VAD_MODEL.exists():
        return "reazon"
    if (WHISPER_ONNX_DIR / "small-tokens.txt").exists() and VAD_MODEL.exists():
        return "whisper-onnx"
    return "faster-whisper"


def available(lang: str = "ja") -> bool:
    eng = resolve_engine(lang)
    if eng in ("reazon", "whisper-onnx"):
        return True
    import importlib.util as u
    return bool(u.find_spec("faster_whisper") or u.find_spec("whisperx"))


def transcribe(wav_path: str, lang: str, progress: Callable[[float], None] | None = None,
               duration: float | None = None) -> dict:
    eng = resolve_engine(lang)
    if eng == "reazon":
        if lang != "ja":
            raise ASRUnavailable("ReazonSpeech chỉ hỗ trợ tiếng Nhật – đặt ASR_ENGINE=whisper-onnx")
        return _sherpa(wav_path, "reazon", lang, progress)
    if eng == "whisper-onnx":
        return _sherpa(wav_path, "whisper-onnx", lang, progress)
    if eng == "whisperx":
        return _whisperx(wav_path, lang)
    return _faster_whisper(wav_path, lang, progress, duration)


# ------------------------------------------------------------------ sherpa-onnx (CPU)
def load_wav(path: str) -> np.ndarray:
    import soundfile as sf
    a, sr = sf.read(path, dtype="float32", always_2d=False)
    if a.ndim > 1:
        a = a.mean(axis=1)
    if sr != SR:
        raise ASRUnavailable(f"Audio phải là {SR} Hz (nhận {sr})")
    return a


def vad_segments(audio: np.ndarray, min_silence: float | None = None, max_speech: float = 12.0) -> list[tuple[float, np.ndarray]]:
    import sherpa_onnx
    if not VAD_MODEL.exists():
        raise ASRUnavailable("Thiếu models/silero_vad.onnx – chạy scripts/download_models.sh")
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(VAD_MODEL)
    cfg.silero_vad.threshold = VAD_THRESHOLD
    cfg.silero_vad.min_silence_duration = VAD_MIN_SILENCE if min_silence is None else min_silence
    cfg.silero_vad.min_speech_duration = 0.15
    cfg.silero_vad.max_speech_duration = max_speech
    cfg.sample_rate = SR
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=max(60, len(audio) / SR + 5))
    w = cfg.silero_vad.window_size
    out = []
    for i in range(0, len(audio), w):
        vad.accept_waveform(audio[i:i + w])
        while not vad.empty():
            out.append((vad.front.start / SR, np.array(vad.front.samples, dtype=np.float32)))
            vad.pop()
    vad.flush()
    while not vad.empty():
        out.append((vad.front.start / SR, np.array(vad.front.samples, dtype=np.float32)))
        vad.pop()
    return out


def denoise(audio: np.ndarray) -> np.ndarray:
    """Khử nhiễu GTCRN (sherpa-onnx). Không có model thì trả nguyên audio."""
    if not DENOISE_MODEL.exists():
        return audio
    import sherpa_onnx
    with _lock:
        if "denoiser" not in _cache:
            cfg = sherpa_onnx.OfflineSpeechDenoiserConfig(model=sherpa_onnx.OfflineSpeechDenoiserModelConfig(
                gtcrn=sherpa_onnx.OfflineSpeechDenoiserGtcrnModelConfig(model=str(DENOISE_MODEL)),
                num_threads=ASR_THREADS))
            _cache["denoiser"] = sherpa_onnx.OfflineSpeechDenoiser(cfg)
    r = _cache["denoiser"](audio, SR)
    return np.array(r.samples, dtype=np.float32)


def _recognizer(kind: str):
    import sherpa_onnx
    with _lock:
        if kind in _cache:
            return _cache[kind]
        if kind == "reazon":
            d = REAZON_DIR
            if not (d / "tokens.txt").exists():
                raise ASRUnavailable("Chưa có model ReazonSpeech – chạy scripts/download_models.sh")
            rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(d / "encoder-epoch-99-avg-1.int8.onnx"),
                decoder=str(d / "decoder-epoch-99-avg-1.int8.onnx"),
                joiner=str(d / "joiner-epoch-99-avg-1.int8.onnx"),
                tokens=str(d / "tokens.txt"), num_threads=ASR_THREADS, decoding_method="greedy_search")
        else:
            d = WHISPER_ONNX_DIR
            if not (d / "small-tokens.txt").exists():
                raise ASRUnavailable("Chưa có model Whisper – chạy scripts/download_models.sh --whisper")
            rec = sherpa_onnx.OfflineRecognizer.from_whisper(
                encoder=str(d / "small-encoder.int8.onnx"), decoder=str(d / "small-decoder.int8.onnx"),
                tokens=str(d / "small-tokens.txt"), language="ja", task="transcribe", num_threads=ASR_THREADS)
        _cache[kind] = rec
        return rec


PAD_SEC = 0.4   # đệm im lặng hai đầu mỗi lượt nói: mẩu ngắn ('まず' 0,4 s) nhận đúng hơn hẳn


def _sherpa(wav_path: str, kind: str, lang: str, progress) -> dict:
    """Nhận dạng TỪNG lượt nói (VAD) riêng, có đệm im lặng.
    Lưu ý: ReazonSpeech được huấn luyện trên câu đơn – đưa cả khối nhiều câu vào thì
    model chỉ trả về một câu, nên không gộp lượt nói trước khi nhận dạng."""
    audio = load_wav(wav_path)
    mode = ASR_DENOISE
    segs = None
    if mode == "auto":
        # thử VAD trên audio gốc; nếu "tiếng nói" phủ gần hết audio (ồn nền liên tục) thì mới khử nhiễu
        segs = vad_segments(audio)
        speech = sum(len(x) for _, x in segs) / SR
        long_share = sum(len(x) for _, x in segs if len(x) / SR > 8) / SR
        noisy = speech > 0.85 * len(audio) / SR or long_share > 0.5 * max(speech, 1e-6)
        mode = "vad" if noisy else "off"
    if mode in ("vad", "both"):
        clean = denoise(audio)
        segs = vad_segments(clean)
        if mode == "vad":   # cắt câu trên audio đã khử nhiễu, nhận dạng trên audio gốc
            segs = [(st, audio[int(st * SR):int(st * SR) + len(smp)]) for st, smp in segs]
        else:
            audio = clean
    elif segs is None:
        segs = vad_segments(audio)
    rec = _recognizer(kind)
    pad = np.zeros(int(PAD_SEC * SR), dtype=np.float32)
    out = []
    pending_onset, last_empty_end = None, -1.0
    batch = 16
    for b in range(0, len(segs), batch):
        chunk = segs[b:b + batch]
        streams = []
        for _, smp in chunk:
            s = rec.create_stream()
            s.accept_waveform(SR, np.concatenate([pad, smp, pad]))
            streams.append(s)
        rec.decode_streams(streams)
        for (start, smp), s in zip(chunk, streams):
            r = s.result
            text = r.text.strip()
            end = start + len(smp) / SR
            if not text or (kind == "whisper-onnx" and HALLUCINATIONS.search(text)):
                # lượt nói không ra chữ (tiếng đệm 'えー', tiếng cười…): nhớ lại để kéo mốc đầu câu kế tiếp
                pending_onset = start if pending_onset is None else pending_onset
                last_empty_end = end
                continue
            if pending_onset is not None and start - last_empty_end <= 0.35:
                start = pending_onset
            pending_onset = None
            words = []
            if kind == "reazon" and r.timestamps:
                ts = [min(max(start, start + t - PAD_SEC), end) for t in r.timestamps]
                for i, tok in enumerate(r.tokens):
                    we = ts[i + 1] if i + 1 < len(ts) else end
                    words.append({"start": round(ts[i], 3), "end": round(max(we, ts[i]), 3), "word": tok})
                words[0]["start"] = round(start, 3)       # mốc đầu/cuối bám ranh giới VAD
                words[-1]["end"] = round(end, 3)
            out.append({"start": round(start, 3), "end": round(end, 3), "text": text, "words": words})
        if progress:
            progress(min(1.0, (b + batch) / max(1, len(segs))))
    return {"segments": out, "engine": kind, "denoise": mode, "audioSec": len(audio) / SR}


# ------------------------------------------------------------------ GPU engines
def _faster_whisper(wav_path, lang, progress, duration):
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise ASRUnavailable(
            "Video chưa có phụ đề nên cần ASR, nhưng chưa có engine nào: chạy scripts/download_models.sh "
            "(ReazonSpeech, CPU) hoặc pip install faster-whisper (GPU), hoặc tải lên file phụ đề.") from e
    key = ("fw", ASR_MODEL, ASR_DEVICE)
    if key not in _cache:
        _cache[key] = WhisperModel(ASR_MODEL, device=ASR_DEVICE, compute_type=ASR_COMPUTE_TYPE)
    segments, info = _cache[key].transcribe(
        wav_path, language=lang, vad_filter=True, word_timestamps=True,
        condition_on_previous_text=False, vad_parameters={"min_silence_duration_ms": 400})
    total = duration or getattr(info, "duration", None) or 0
    out = []
    for s in segments:
        if s.no_speech_prob > 0.6 or HALLUCINATIONS.search(s.text):
            continue
        out.append({"start": s.start, "end": s.end, "text": s.text.strip(),
                    "words": [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()} for w in s.words or []]})
        if progress and total:
            progress(min(1.0, s.end / total))
    return {"segments": out, "engine": "faster-whisper"}


def _whisperx(wav_path, lang):
    try:
        import whisperx
    except ImportError as e:
        raise ASRUnavailable("Chưa cài whisperx (pip install whisperx)") from e
    device = "cpu"
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        pass
    model = whisperx.load_model(ASR_MODEL, device, compute_type="float16" if device == "cuda" else "int8", language=lang)
    audio = whisperx.load_audio(wav_path)
    result = model.transcribe(audio, batch_size=16, language=lang)
    align_model, meta = whisperx.load_align_model(language_code=lang, device=device)
    aligned = whisperx.align(result["segments"], align_model, meta, audio, device)
    out = []
    for s in aligned["segments"]:
        if HALLUCINATIONS.search(s.get("text", "")):
            continue
        out.append({"start": s["start"], "end": s["end"], "text": s["text"].strip(),
                    "words": [{"start": round(w["start"], 3), "end": round(w["end"], 3), "word": w["word"].strip()}
                              for w in s.get("words", []) if "start" in w]})
    return {"segments": out, "engine": "whisperx"}
