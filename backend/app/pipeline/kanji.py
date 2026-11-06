"""Thông tin kanji từ KANJIDIC2 (EDRDG, CC BY-SA 4.0): âm On/Kun, âm Hán Việt, nghĩa tiếng Anh, số nét.

Nghĩa tiếng Việt: cache dùng chung (DATA_DIR/cache/kanji_vi.json). Kanji chưa có nghĩa tiếng Việt thì
hỏi LLM một lần (Translator._kanji_meanings) rồi lưu lại – tập sau không tốn token cho kanji đó nữa.
"""
from __future__ import annotations

import gzip
import json
import threading
from functools import lru_cache
from pathlib import Path

from ..config import DATA_DIR

_DIC = Path(__file__).resolve().parents[1] / "data" / "kanjidic.json.gz"
_CACHE = DATA_DIR / "cache" / "kanji_vi.json"
_lock = threading.Lock()


@lru_cache(maxsize=1)
def _dic() -> dict:
    with gzip.open(_DIC, "rt", encoding="utf-8") as f:
        return json.load(f)


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def han_viet(ch: str) -> str:
    return "/".join(v.upper() for v in _dic().get(ch, {}).get("vi", [])[:2])


def english(ch: str) -> str:
    return ", ".join(_dic().get(ch, {}).get("en", [])[:3])


def lookup(ch: str, vi_cache: dict | None = None) -> dict:
    d = _dic().get(ch, {})
    vi = (vi_cache if vi_cache is not None else _load_cache()).get(ch, "")
    return {"char": ch, "on": d.get("on", []), "kun": d.get("kun", []), "hanViet": han_viet(ch),
            "meaning": vi or english(ch), "meaningLang": "vi" if vi else "en",
            "strokes": d.get("strokes"), "source": "KANJIDIC2"}


def lookup_many(chars: list[str]) -> list[dict]:
    cache = _load_cache()
    return [lookup(ch, cache) for ch in chars]


def ensure_vi_meanings(chars: list[str], fetch) -> int:
    """Bổ sung nghĩa tiếng Việt cho kanji chưa có trong cache bằng fetch(list) -> {char: nghĩa}."""
    with _lock:
        cache = _load_cache()
        todo = [c for c in chars if c not in cache and c in _dic()]
        if not todo:
            return 0
        got = fetch(todo)
        cache.update({k: v for k, v in got.items() if v})
        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
        return len(got)
