"""Đọc phụ đề có sẵn (.srt/.vtt/.ass) → danh sách cue thô {start,end,text}."""
from __future__ import annotations

from pathlib import Path

import pysubs2

from .cues import normalize_text


def parse_subtitle_file(path: str | Path) -> list[dict]:
    subs = pysubs2.load(str(path), encoding="utf-8")
    cues: list[dict] = []
    for ev in subs:
        if ev.is_comment:
            continue
        text = normalize_text(ev.plaintext)
        if not text:
            continue
        start, end = ev.start / 1000, ev.end / 1000
        # VTT tự động của YouTube lặp lại dòng trước (kiểu "cuộn") → bỏ trùng
        if cues and text == cues[-1]["text"] and start - cues[-1]["end"] < 0.5:
            cues[-1]["end"] = end
            continue
        cues.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    cues.sort(key=lambda c: c["start"])
    return cues
