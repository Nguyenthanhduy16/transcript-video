"""Dịch nhanh đoạn văn bôi đen (extension "dịch khi bôi đen") bằng Claude.

- 1–3 từ: trả thêm thông tin kiểu từ điển (dạng gốc, phiên âm IPA, loại từ, các nghĩa, câu ví dụ).
- Dài hơn: chỉ bản dịch tự nhiên.
Kết quả được cache trong bộ nhớ (bôi đen lại cùng đoạn → trả ngay, không tốn token).
"""
from __future__ import annotations

import re
import threading
from collections import OrderedDict

from pydantic import BaseModel, Field

from .translate import LANG_NAMES, Translator

MAX_CHARS = 5000
_cache: OrderedDict[tuple, dict] = OrderedDict()
_lock = threading.Lock()


class TextOut(BaseModel):
    translation: str = Field(description="Bản dịch tự nhiên, giữ nguyên xuống dòng và định dạng danh sách")
    detectedLang: str = Field(description="Mã ISO 639-1 của ngôn ngữ gốc, vd. en, ja")


class WordOut(BaseModel):
    translation: str = Field(description="Nghĩa phù hợp nhất, ngắn gọn")
    detectedLang: str
    lemma: str = Field(description="Dạng gốc (từ điển) của từ/cụm")
    ipa: str = Field(description="Phiên âm IPA (tiếng Anh) hoặc cách đọc kana (tiếng Nhật); rỗng nếu không áp dụng")
    pos: str = Field(description="Loại từ bằng tiếng Việt, vd. động từ, danh từ, cụm động từ")
    meanings: list[str] = Field(description="1–4 nghĩa thường gặp, mỗi nghĩa ngắn")
    example: str = Field(description="Một câu ví dụ ngắn bằng ngôn ngữ gốc")
    exampleVi: str = Field(description="Bản dịch câu ví dụ")


def _is_short(text: str) -> bool:
    return len(text) <= 40 and len(re.findall(r"\S+", text)) <= 3 and "\n" not in text


def translate(text: str, target: str = "vi", source: str = "auto") -> dict:
    text = text.strip()
    if not text:
        raise ValueError("Đoạn văn trống")
    if len(text) > MAX_CHARS:
        raise ValueError(f"Đoạn văn dài hơn {MAX_CHARS} ký tự")
    key = (text, target, source)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return {**_cache[key], "cached": True}
    tgt = LANG_NAMES.get(target, target)
    short = _is_short(text)
    tr = Translator(source if source != "auto" else "en", target)
    system = (f"Bạn là từ điển và biên dịch viên cho người Việt. Dịch sang {tgt}. "
              + ("Người dùng bôi đen một từ/cụm từ khi đọc tài liệu: trả nghĩa đúng nhất, dạng gốc, phiên âm, "
                 "loại từ, các nghĩa thường gặp và một câu ví dụ." if short else
                 "Dịch tự nhiên, chính xác thuật ngữ chuyên ngành (giữ nguyên tên riêng, mã lệnh, công thức), "
                 "giữ nguyên xuống dòng và gạch đầu dòng. Chỉ trả bản dịch, không giải thích."))
    out = tr._parse(system, text, WordOut if short else TextOut, 4000, effort="low")
    res = {**out.model_dump(), "kind": "word" if short else "text", "engine": "claude", "usage": tr.usage_summary()}
    with _lock:
        _cache[key] = res
        while len(_cache) > 1000:
            _cache.popitem(last=False)
    return res
