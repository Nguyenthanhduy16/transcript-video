"""Dịch + phân tích ngôn ngữ bằng Claude (structured outputs), theo lô 20–50 cue kèm ngữ cảnh.

Một lần gọi trả về cho mỗi cue: bản dịch, nghĩa tiếng Việt + JLPT cho các từ vựng do Sudachi tách,
kanji (On/Kun/Hán Việt) và mẫu ngữ pháp. Nếu không có thông tin xác thực (LLM_PROVIDER=none
hoặc không có API key) thì bỏ qua bước này và ghi cảnh báo.
"""
from __future__ import annotations

import json
import logging
from typing import Callable

from pydantic import BaseModel, Field

from ..config import (LLM_BATCH_SIZE, LLM_CONTEXT_AFTER, LLM_CONTEXT_BEFORE, LLM_EFFORT, LLM_MODEL,
                      LLM_PROVIDER)

log = logging.getLogger(__name__)

LANG_NAMES = {"ja": "tiếng Nhật", "ko": "tiếng Hàn", "zh": "tiếng Trung", "en": "tiếng Anh", "vi": "tiếng Việt"}


# ------------------------------------------------------------------ schema đầu ra
class VocabOut(BaseModel):
    lemma: str = Field(description="Dạng từ điển, đúng như trong danh sách ứng viên")
    reading: str = Field(description="Cách đọc hiragana của dạng từ điển")
    meaning: str = Field(description="Nghĩa tiếng Việt ngắn gọn, đúng ngữ cảnh câu")
    jlpt: str = Field(description="N5, N4, N3, N2, N1 hoặc chuỗi rỗng nếu không thuộc JLPT")


class KanjiOut(BaseModel):
    char: str
    on: list[str] = Field(description="Âm On (katakana)")
    kun: list[str] = Field(description="Âm Kun (hiragana)")
    hanViet: str = Field(description="Âm Hán Việt, viết hoa, vd. 'TÚC ĐỀ'")
    meaning: str = Field(description="Nghĩa tiếng Việt")


class GrammarOut(BaseModel):
    pattern: str = Field(description="Mẫu ngữ pháp, vd. '〜たらあかん'")
    meaning: str = Field(description="Ý nghĩa ngắn")
    explanation: str = Field(description="Giải thích 1–2 câu tiếng Việt, nêu cả sắc thái (khẩu ngữ, phương ngữ...)")
    jlpt: str = Field(description="N5–N1 hoặc rỗng")


class CueOut(BaseModel):
    id: int
    translation: str
    vocab: list[VocabOut]
    kanji: list[KanjiOut]
    grammar: list[GrammarOut]


class BatchOut(BaseModel):
    cues: list[CueOut]


class LLMUnavailable(RuntimeError):
    pass


SYSTEM_PROMPT = """Bạn là biên dịch viên phụ đề và giáo viên ngôn ngữ cho người Việt học {src}.
Nhiệm vụ: với mỗi câu thoại trong mục CẦN XỬ LÝ, trả về bản dịch tiếng Việt và phần phân tích.

Quy tắc dịch:
- Dịch tự nhiên như phụ đề phim Việt, ngắn gọn, đọc kịp theo tốc độ video.
- Giữ giọng nhân vật: khẩu ngữ, cộc cằn, nhõng nhẽo, kính ngữ... Phương ngữ (vd. Kansai) thì dùng
  văn nói Việt suồng sã tương ứng, không chuyển thành văn chuẩn.
- Xưng hô nhất quán theo quan hệ nhân vật và theo phần NGỮ CẢNH đã dịch trước đó.
- Nếu câu gốc chứa nhãn người nói trong ngoặc như （チエ）, giữ nhãn ở vị trí tương ứng bằng tên
  phiên âm Latin trong ngoặc tròn, vd. "(Chie) Về nha. (Hirame) Về nha.". Không tự thêm nhãn nếu
  câu gốc không có.
- Tên riêng dùng theo BẢNG THUẬT NGỮ nếu có.
- Phần NGỮ CẢNH chỉ để tham khảo, không trả về.

Quy tắc phân tích:
- vocab: chỉ điền cho đúng các từ trong "ung_vien_tu_vung" của câu đó (giữ nguyên lemma),
  nghĩa phải hợp ngữ cảnh câu. Bỏ qua tên người.
- kanji: đúng các chữ trong "kanji" của câu đó.
- grammar: 0–3 mẫu ngữ pháp/cấu trúc đáng học nhất trong câu (kể cả dạng khẩu ngữ, phương ngữ).
- Trả về đủ mọi id trong CẦN XỬ LÝ, đúng thứ tự."""


class Translator:
    def __init__(self, src_lang: str = "ja", target: str = "vi", glossary: str = ""):
        if LLM_PROVIDER == "none":
            raise LLMUnavailable("LLM_PROVIDER=none")
        try:
            import anthropic
            self.anthropic = anthropic
            self.client = anthropic.Anthropic()
        except Exception as e:  # thiếu SDK / thiếu thông tin xác thực
            raise LLMUnavailable(str(e)) from e
        self.src_lang = src_lang
        self.target = target
        self.system = SYSTEM_PROMPT.format(src=LANG_NAMES.get(src_lang, src_lang))
        if target != "vi":
            self.system += f"\nNgôn ngữ đích: {LANG_NAMES.get(target, target)} (thay cho tiếng Việt)."
        if glossary.strip():
            self.system += "\n\nBẢNG THUẬT NGỮ / GHI CHÚ SERIES:\n" + glossary.strip()

    # ---------------------------------------------------------------- 1 lô
    def _call(self, payload: dict) -> BatchOut:
        a = self.anthropic
        try:
            resp = self.client.beta.messages.parse(
                model=LLM_MODEL,
                max_tokens=16000,   # non-streaming: giữ ≤16k để tránh timeout HTTP
                system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)}],
                output_format=BatchOut,
                output_config={"effort": LLM_EFFORT},
                # tự chuyển model khác nếu bị từ chối do bộ lọc an toàn
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except a.AuthenticationError as e:
            raise LLMUnavailable(f"Sai/thiếu API key: {e}") from e
        except a.PermissionDeniedError as e:
            raise LLMUnavailable(f"Không có quyền dùng model {LLM_MODEL}: {e}") from e
        except TypeError as e:   # SDK không tìm thấy API key / profile
            if "authentication" in str(e).lower():
                raise LLMUnavailable("chưa có ANTHROPIC_API_KEY") from e
            raise
        if resp.stop_reason == "refusal":
            raise RuntimeError("Model từ chối xử lý lô này")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Đầu ra bị cắt (max_tokens) – giảm LLM_BATCH_SIZE")
        if resp.parsed_output is None:
            raise RuntimeError("Không đọc được JSON trả về")
        return resp.parsed_output

    def process(self, cues: list[dict], progress: Callable[[float], None] | None = None,
                only_ids: set[int] | None = None) -> list[str]:
        """Điền translation/vocab/kanji/grammar vào các cue speech. Trả về danh sách cảnh báo."""
        warnings: list[str] = []
        speech = [c for c in cues if c["type"] == "speech" and (only_ids is None or c["id"] in only_ids)]
        index = {c["id"]: i for i, c in enumerate(cues)}
        batches = [speech[i:i + LLM_BATCH_SIZE] for i in range(0, len(speech), LLM_BATCH_SIZE)]
        for bi, batch in enumerate(batches):
            first, last = index[batch[0]["id"]], index[batch[-1]["id"]]
            before = [c for c in cues[max(0, first - LLM_CONTEXT_BEFORE * 2):first] if c["type"] == "speech"][-LLM_CONTEXT_BEFORE:]
            after = [c for c in cues[last + 1:last + 1 + LLM_CONTEXT_AFTER * 2] if c["type"] == "speech"][:LLM_CONTEXT_AFTER]
            payload = {
                "NGU_CANH_TRUOC": [{"nguoi_noi": c.get("speaker"), "goc": c["text"], "dich": c.get("translation", "")} for c in before],
                "CAN_XU_LY": [{
                    "id": c["id"], "nguoi_noi": c.get("speaker"), "goc": c["text"],
                    "ung_vien_tu_vung": [v["lemma"] for v in c.get("_cand", [])],
                    "kanji": c.get("_kanji", []),
                } for c in batch],
                "NGU_CANH_SAU": [{"nguoi_noi": c.get("speaker"), "goc": c["text"]} for c in after],
            }
            result = None
            for attempt in range(2):
                try:
                    result = self._call(payload)
                    break
                except LLMUnavailable:
                    raise
                except Exception as e:  # lỗi tạm thời / JSON hỏng → thử lại 1 lần
                    log.warning("Lô %d lỗi (lần %d): %s", bi, attempt + 1, e)
                    if attempt == 1:
                        warnings.append(f"Lô {bi + 1}: {e}")
            if result:
                by_id = {o.id: o for o in result.cues}
                missing = [c["id"] for c in batch if c["id"] not in by_id]
                if missing:
                    warnings.append(f"Lô {bi + 1}: thiếu kết quả cho cue {missing}")
                for c in batch:
                    o = by_id.get(c["id"])
                    if o:
                        _merge(c, o)
            if progress:
                progress((bi + 1) / len(batches))
        return warnings


def _merge(cue: dict, o: CueOut) -> None:
    cue["translation"] = o.translation.strip()
    cand = {v["lemma"]: v for v in cue.get("_cand", [])}
    vocab = []
    for v in o.vocab:
        base = cand.get(v.lemma, {})
        vocab.append({"lemma": v.lemma, "reading": v.reading or base.get("reading", ""),
                      "pos": base.get("pos", ""), "meaning": v.meaning, "jlpt": v.jlpt or None})
    # từ ứng viên mà LLM bỏ sót vẫn giữ (chưa có nghĩa)
    got = {v["lemma"] for v in vocab}
    vocab += [{**b, "meaning": "", "jlpt": None} for k, b in cand.items() if k not in got]
    cue["vocab"] = vocab
    cue["kanji"] = [k.model_dump() for k in o.kanji]
    cue["grammar"] = [g.model_dump() for g in o.grammar]
