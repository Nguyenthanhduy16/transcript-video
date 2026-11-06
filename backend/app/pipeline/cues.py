"""Phân loại cue (speech/music/sfx), tách nhãn người nói, chia/gộp cue theo độ dài."""
from __future__ import annotations

import re

from ..config import CUE_MAX_CHARS, CUE_MAX_SEC, CUE_MIN_SEC, CUE_PAUSE_SPLIT_SEC

MUSIC_RE = re.compile(r"^[\s♪♫♬～〜~・…\-ー]*$")
PAREN_ONLY_RE = re.compile(r"^\s*([（(\[［【][^）)\]］】]{1,20}[）)\]］】]\s*)+$")
LEADING_TAG_RE = re.compile(r"^\s*[（(]([^（）()]{1,12})[）)]\s*")
ANY_TAG_RE = re.compile(r"[（(]([^（）()]{1,12})[）)]")
LAUGH_WORDS = ("笑", "笑い声", "笑う")
SENT_END = "。！？!?…"


def classify(text: str) -> str:
    """speech | music | sfx."""
    t = text.strip()
    if not t:
        return "sfx"
    if "♪" in t or "♫" in t:
        # chỉ toàn ký hiệu nhạc → music; có lời bài hát giữa ♪ ♪ vẫn là music (không cần học)
        return "music"
    if MUSIC_RE.match(t) and any(c in t for c in "～〜"):
        return "music"
    if PAREN_ONLY_RE.match(t):
        return "sfx"          # （チャイム） （笑い声） （拍手）
    return "speech"


def split_speaker(text: str) -> tuple[str | None, str, bool]:
    """'（チエ）さいなら' → ('チエ', 'さいなら', False).

    Cue có nhiều người nói ('（チエ）さいなら（ヒラメ）さいなら') giữ nguyên nhãn trong text,
    speaker = người đầu tiên, multi=True.
    """
    t = text.strip()
    tags = [m for m in ANY_TAG_RE.finditer(t)]
    # chỉ coi là nhãn người nói nếu theo sau là lời thoại
    speaker_tags = [m for m in tags if t[m.end():].strip() and not t[m.end():].lstrip().startswith(("（", "("))]
    if not speaker_tags or not LEADING_TAG_RE.match(t):
        return None, t, False
    first = LEADING_TAG_RE.match(t)
    if len(speaker_tags) == 1:
        return first.group(1), t[first.end():].strip(), False
    return first.group(1), t, True


def normalize_text(text: str) -> str:
    t = text.replace("\\N", " ").replace("\n", " ")
    t = re.sub(r"<[^>]+>", "", t)          # thẻ HTML/VTT
    t = re.sub(r"\{[^}]*\}", "", t)        # thẻ ASS
    t = re.sub(r"[ 　]+", " ", t)
    return t.strip()


# ------------------------------------------------------------ chia cue từ ASR (mức từ)
def cues_from_words(words: list[dict]) -> list[dict]:
    """words: [{"start","end","word"}] (mốc thời gian từng từ) → cue 1–7 s, ≤ CUE_MAX_CHARS ký tự."""
    cues: list[dict] = []
    cur: list[dict] = []

    def flush():
        if cur:
            text = "".join(w["word"] for w in cur).strip()
            if text:
                cues.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": text})
            cur.clear()

    for w in words:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            dur = w["end"] - cur[0]["start"]
            chars = sum(len(x["word"]) for x in cur) + len(w["word"])
            if gap >= CUE_PAUSE_SPLIT_SEC or dur > CUE_MAX_SEC or chars > CUE_MAX_CHARS:
                flush()
        cur.append(w)
        last = w["word"].strip()
        if last and last[-1] in SENT_END and (cur[-1]["end"] - cur[0]["start"]) >= CUE_MIN_SEC:
            flush()
    flush()
    return merge_short(cues)


def cues_from_segments(segments: list[dict]) -> list[dict]:
    """Khi không có mốc từng từ: tách segment dài theo dấu câu, chia thời gian theo số ký tự."""
    out = []
    for s in segments:
        out.extend(split_long_cue(s))
    return merge_short(out)


def split_long_cue(c: dict) -> list[dict]:
    text = c["text"]
    dur = c["end"] - c["start"]
    if dur <= CUE_MAX_SEC and len(text) <= CUE_MAX_CHARS * 1.5:
        return [c]
    parts = [p for p in re.split(r"(?<=[。！？!?])\s*", text) if p.strip()]
    if len(parts) < 2:
        parts = [p for p in re.split(r"(?<=[、 ])", text) if p.strip()]
    if len(parts) < 2:
        return [c]
    # gộp các mảnh để mỗi phần gần CUE_MAX_CHARS
    chunks: list[str] = []
    for p in parts:
        if chunks and len(chunks[-1]) + len(p) <= CUE_MAX_CHARS:
            chunks[-1] += p
        else:
            chunks.append(p)
    total = sum(len(x) for x in chunks)
    out, t = [], c["start"]
    for ch in chunks:
        d = dur * len(ch) / total
        out.append({**c, "start": round(t, 3), "end": round(t + d, 3), "text": ch.strip()})
        t += d
    out[-1]["end"] = c["end"]
    return out


def merge_short(cues: list[dict]) -> list[dict]:
    """Gộp cue < 1 s vào cue kề nếu khoảng lặng nhỏ và tổng vẫn hợp lệ."""
    out: list[dict] = []
    for c in cues:
        if out:
            p = out[-1]
            short = (c["end"] - c["start"] < CUE_MIN_SEC) or (p["end"] - p["start"] < CUE_MIN_SEC)
            if (short and c["start"] - p["end"] < 0.3 and c["end"] - p["start"] <= CUE_MAX_SEC
                    and len(p["text"]) + len(c["text"]) <= CUE_MAX_CHARS
                    and p.get("speaker") == c.get("speaker")
                    and p["text"][-1:] not in SENT_END):
                p["end"] = c["end"]
                p["text"] = p["text"] + c["text"]
                continue
        out.append(dict(c))
    return out


def ensure_min_duration(cues: list[dict]) -> None:
    """Kéo dài cue quá ngắn (nếu không đè cue sau) để người học kịp đọc."""
    for i, c in enumerate(cues):
        if c["end"] - c["start"] < CUE_MIN_SEC:
            limit = cues[i + 1]["start"] if i + 1 < len(cues) else c["start"] + CUE_MIN_SEC
            c["end"] = round(min(c["start"] + CUE_MIN_SEC, max(limit, c["end"])), 3)
