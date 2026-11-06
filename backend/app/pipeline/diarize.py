"""Gán người nói.

- embedding (mặc định): mỗi câu thoại → vector giọng (3D-Speaker ERes2Net, sherpa-onnx, CPU),
  gom cụm phân cấp: không biết số người → average linkage, cắt ở khoảng cách cosine 0,5;
  biết số người (num_speakers) → Ward, cắt đúng số cụm. Không cần token, chạy nhanh trên CPU.
- pyannote: DIARIZE=pyannote + HF_TOKEN + pip install pyannote.audio.
Nhãn đặt theo thứ tự xuất hiện: "Người 1", "Người 2"… – biên tập viên đổi tên trong trang Sửa.
"""
from __future__ import annotations

import logging

import numpy as np

from ..config import ASR_THREADS, DIARIZE, DIARIZE_THRESHOLD, HF_TOKEN, MODELS_DIR

log = logging.getLogger(__name__)
EMB_MODEL = MODELS_DIR / "3dspeaker_eres2net_base.onnx"
MIN_SEG_SEC = 0.5          # câu ngắn hơn: embedding kém tin cậy → gán theo câu gần nhất
_extractor = None


def mode() -> str:
    if DIARIZE == "off":
        return "off"
    if DIARIZE == "pyannote":
        return "pyannote" if HF_TOKEN else "off"
    return "embedding" if EMB_MODEL.exists() else "off"


def available() -> bool:
    return mode() != "off"


def _get_extractor():
    global _extractor
    if _extractor is None:
        import sherpa_onnx
        _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(EMB_MODEL), num_threads=ASR_THREADS))
    return _extractor


def embed(audio: np.ndarray, sr: int = 16000) -> np.ndarray:
    ex = _get_extractor()
    s = ex.create_stream()
    s.accept_waveform(sr, audio)
    s.input_finished()
    e = np.array(ex.compute(s), dtype=np.float32)
    return e / (np.linalg.norm(e) + 1e-9)


def cluster(E: np.ndarray, num_speakers: int | None = None, threshold: float = DIARIZE_THRESHOLD) -> np.ndarray:
    from scipy.cluster.hierarchy import fcluster, linkage
    if len(E) == 1:
        return np.array([1])
    if num_speakers:
        # biết số người nói: Ward trên vector đã chuẩn hoá (đo trên bộ benchmark: tốt hơn average + maxclust)
        return fcluster(linkage(E, method="ward"), num_speakers, "maxclust")
    return fcluster(linkage(E, method="average", metric="cosine"), threshold, "distance")


def assign_by_embedding(cues: list[dict], audio: np.ndarray, num_speakers: int | None = None,
                        sr: int = 16000) -> int:
    """Điền cue['speaker'] cho các câu speech chưa có người nói. Trả về số người nói tìm được."""
    idx = [i for i, c in enumerate(cues) if c["type"] == "speech" and not c.get("speaker")]
    long_idx = [i for i in idx if cues[i]["end"] - cues[i]["start"] >= MIN_SEG_SEC]
    if not long_idx:
        return 0
    E = np.stack([embed(audio[int(cues[i]["start"] * sr):int(cues[i]["end"] * sr)], sr) for i in long_idx])
    labels = cluster(E, num_speakers)
    # đặt tên theo thứ tự xuất hiện
    names: dict[int, str] = {}
    for i, lab in zip(long_idx, labels):
        names.setdefault(int(lab), f"Người {len(names) + 1}")
        cues[i]["speaker"] = names[int(lab)]
    # câu ngắn: lấy người nói của câu dài gần nhất về thời gian
    for i in idx:
        if cues[i].get("speaker"):
            continue
        j = min(long_idx, key=lambda k: abs(cues[k]["start"] - cues[i]["start"]))
        cues[i]["speaker"] = cues[j]["speaker"]
    return len(names)


def diarize_pyannote(wav_path: str) -> list[tuple[float, float, str]]:
    from pyannote.audio import Pipeline
    pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=HF_TOKEN)
    ann = pipe(wav_path)
    return [(t.start, t.end, spk) for t, _, spk in ann.itertracks(yield_label=True)]


def assign_from_turns(cues: list[dict], turns: list[tuple[float, float, str]]) -> None:
    names: dict[str, str] = {}
    for c in cues:
        if c.get("speaker") or c["type"] != "speech":
            continue
        best, best_ov = None, 0.0
        for s, e, spk in turns:
            ov = min(e, c["end"]) - max(s, c["start"])
            if ov > best_ov:
                best, best_ov = spk, ov
        if best:
            names.setdefault(best, f"Người {len(names) + 1}")
            c["speaker"] = names[best]
