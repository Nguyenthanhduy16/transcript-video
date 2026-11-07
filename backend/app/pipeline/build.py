"""Ghép các bước thành transcript JSON hoàn chỉnh."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from . import english, japanese, kanji as kanjidic
from .cues import classify, split_speaker

SPEAKER_COLORS = ["#F4A261", "#E76F51", "#2A9D8F", "#8AB17D", "#E9C46A", "#9B5DE5",
                  "#F15BB5", "#00BBF9", "#00C49A", "#FF6B6B", "#6C8EBF", "#B5838D"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_cues(raw: list[dict], lang: str) -> list[dict]:
    """raw {start,end,text[,speaker]} → cue có id, type, speaker."""
    cues = []
    for c in raw:
        text = c["text"].strip()
        ctype = classify(text)
        speaker, multi = c.get("speaker"), False
        if ctype == "speech":
            sp, text, multi = split_speaker(text)
            speaker = speaker or sp
        cues.append({"id": 0, "start": round(c["start"], 3), "end": round(c["end"], 3),
                     "speaker": speaker, "type": ctype, "text": text, "multiSpeaker": multi})
    cues.sort(key=lambda x: x["start"])
    # mốc end giữ đúng lúc hết tiếng nói (để đồng bộ/tự dừng chính xác);
    # thời gian hiển thị tối thiểu 1 s do frontend lo.
    for i, c in enumerate(cues, 1):
        c["id"] = i
    return cues


def enrich_cue(c: dict, lang: str) -> None:
    """Tách từ, furigana, romaji, ứng viên từ vựng & kanji (không cần LLM)."""
    c.setdefault("translation", "")
    if c["type"] != "speech":
        c.update(tokens=[], romaji="", vocab=[], kanji=[], grammar=[])
        c["translation"] = ""        # nhạc/tiếng động: không dịch
        return
    if lang == "ja":
        toks = japanese.tokenize(c["text"])
        c["tokens"] = toks
        c["romaji"] = japanese.romaji_line(toks)
        c["_cand"] = japanese.vocab_candidates(toks)
        c["_kanji"] = japanese.extract_kanji(c["text"])
    elif lang == "en":
        toks = english.tokenize(c["text"])
        c["tokens"] = toks
        c["romaji"] = ""
        c["_cand"] = english.vocab_candidates(toks)
        c["_kanji"] = []
    else:
        c["tokens"] = [{"surface": w, "reading": "", "lemma": w, "pos": "", "furigana": [[w, None]],
                        "romaji": "", "isWord": True} for w in c["text"].split()]
        c["romaji"] = ""
        c["_cand"] = [{"lemma": w, "reading": "", "pos": ""} for w in dict.fromkeys(c["text"].split())]
        c["_kanji"] = []
    # giá trị mặc định khi chưa có LLM
    c.setdefault("vocab", [{**v, "meaning": "", "jlpt": None} for v in c["_cand"]])
    c.setdefault("kanji", kanjidic.lookup_many(c["_kanji"]))       # KANJIDIC2: On/Kun/Hán Việt (không cần LLM)
    c.setdefault("grammar", [])


def strip_private(cues: list[dict]) -> None:
    for c in cues:
        c.pop("_cand", None)
        c.pop("_kanji", None)


def build_speakers(cues: list[dict], existing: list[dict] | None = None) -> list[dict]:
    known = {s["name"]: s for s in (existing or [])}
    names: list[str] = []
    for c in cues:
        sp = c.get("speaker")
        if sp and sp not in names:
            names.append(sp)
        if c.get("multiSpeaker"):
            for m in japanese.SPEAKER_TAG_RE.finditer(c["text"]):
                if m.group(1) not in names:
                    names.append(m.group(1))
    out = []
    for i, n in enumerate(names):
        out.append(known.get(n) or {"name": n, "display": n, "color": SPEAKER_COLORS[i % len(SPEAKER_COLORS)]})
    return out


def compute_version(doc: dict) -> str:
    payload = json.dumps([[c["start"], c["end"], c.get("speaker"), c["text"], c.get("translation")]
                          for c in doc["cues"]], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:6]


def finalize(doc: dict) -> dict:
    strip_private(doc["cues"])
    doc["speakers"] = build_speakers(doc["cues"], doc.get("speakers"))
    doc["version"] = compute_version(doc)
    doc["updatedAt"] = now_iso()
    d = datetime.now()
    doc["credit"] = f"sub {d.day}/{d.month} · {doc['version']}"
    return doc
