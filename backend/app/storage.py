"""Lưu transcript JSON trên đĩa (thay bằng PostgreSQL/S3 khi lên production)."""
import json
import re
import threading
from pathlib import Path

from .config import VIDEOS_DIR

_lock = threading.Lock()
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")


def _path(video_id: str) -> Path:
    if not _ID_RE.match(video_id):
        raise ValueError("videoId không hợp lệ")
    return VIDEOS_DIR / f"{video_id}.json"


def save_transcript(doc: dict) -> None:
    p = _path(doc["videoId"])
    tmp = p.with_suffix(".tmp")
    with _lock:
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)


def load_transcript(video_id: str) -> dict | None:
    p = _path(video_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def list_transcripts() -> list[dict]:
    out = []
    for p in sorted(VIDEOS_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append({
            "videoId": d["videoId"], "title": d.get("title"), "series": d.get("series"),
            "episode": d.get("episode"), "lang": d.get("lang"), "target": d.get("target"),
            "duration": d.get("duration"), "player": d.get("player"),
            "cueCount": len(d.get("cues", [])), "version": d.get("version"),
            "updatedAt": d.get("updatedAt"),
        })
    return out


def delete_transcript(video_id: str) -> bool:
    p = _path(video_id)
    if p.exists():
        p.unlink()
        return True
    return False
