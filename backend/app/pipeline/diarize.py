"""Gán người nói bằng pyannote (tuỳ chọn). Cần: pip install pyannote.audio + HF_TOKEN."""
from __future__ import annotations

import logging

from ..config import DIARIZE, HF_TOKEN

log = logging.getLogger(__name__)


def available() -> bool:
    if DIARIZE == "off" or not HF_TOKEN:
        return False
    try:
        import pyannote.audio  # noqa: F401
        return True
    except ImportError:
        return False


def diarize(wav_path: str) -> list[tuple[float, float, str]]:
    from pyannote.audio import Pipeline
    pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=HF_TOKEN)
    try:
        import torch
        if torch.cuda.is_available():
            pipe.to(torch.device("cuda"))
    except ImportError:
        pass
    ann = pipe(wav_path)
    return [(t.start, t.end, spk) for t, _, spk in ann.itertracks(yield_label=True)]


def assign_speakers(cues: list[dict], turns: list[tuple[float, float, str]]) -> None:
    """Mỗi cue lấy người nói có thời lượng chồng lấn lớn nhất. Nhãn SPEAKER_00 → 'Người 1'."""
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
