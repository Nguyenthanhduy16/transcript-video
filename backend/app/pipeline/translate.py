"""Dịch + phân tích ngôn ngữ bằng Claude (structured outputs), theo lô 20–50 cue kèm ngữ cảnh.

Tối ưu chi phí (P1-5):
- Kanji (On/Kun/Hán Việt) lấy từ KANJIDIC2 (app/pipeline/kanji.py) – không tốn token.
  Chỉ nghĩa tiếng Việt của kanji CHƯA từng gặp mới hỏi LLM (1 lần), lưu cache dùng cho mọi tập sau.
- Cách đọc từ vựng lấy từ SudachiPy; LLM chỉ trả nghĩa + JLPT.
- Payload JSON gọn (không thụt lề), system prompt được cache (prompt caching).
- Chạy song song LLM_CONCURRENCY lô; mỗi lô kèm ngữ cảnh câu gốc trước/sau.
- Ghi số token thật (usage) và chi phí vào doc["stats"]["llmUsage"].
Không có thông tin xác thực (LLM_PROVIDER=none / không có API key) → bỏ qua, ghi cảnh báo.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from pydantic import BaseModel, Field

from ..config import (LLM_ANALYSIS_MODEL, LLM_BATCH_SIZE, LLM_CONTEXT_AFTER, LLM_CONTEXT_BEFORE, LLM_EFFORT,
                      LLM_MODEL, LLM_PROVIDER)
from . import kanji as kanjidic

log = logging.getLogger(__name__)
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "4"))
LANG_NAMES = {"ja": "tiếng Nhật", "ko": "tiếng Hàn", "zh": "tiếng Trung", "en": "tiếng Anh", "vi": "tiếng Việt"}


# ------------------------------------------------------------------ schema đầu ra
class VocabOut(BaseModel):
    lemma: str = Field(description="Dạng từ điển, đúng như trong danh sách tu_vung")
    meaning: str = Field(description="Nghĩa tiếng Việt ngắn gọn (≤ 8 từ), đúng ngữ cảnh câu")
    jlpt: str = Field(description="Cấp độ: tiếng Nhật JLPT N5–N1; tiếng Anh CEFR A1–C2; không rõ thì chuỗi rỗng")


class GrammarOut(BaseModel):
    pattern: str = Field(description="Mẫu ngữ pháp, vd. '〜たらあかん'")
    meaning: str = Field(description="Ý nghĩa ngắn")
    explanation: str = Field(description="1 câu tiếng Việt, nêu sắc thái (khẩu ngữ, phương ngữ…)")
    jlpt: str = Field(description="JLPT N5–N1 (tiếng Nhật) / CEFR A1–C2 (tiếng Anh) hoặc rỗng")


class CueOut(BaseModel):
    id: int
    translation: str
    vocab: list[VocabOut]
    grammar: list[GrammarOut]


class BatchOut(BaseModel):
    cues: list[CueOut]


class TransOut(BaseModel):
    id: int
    translation: str


class TransBatch(BaseModel):
    cues: list[TransOut]


class AnaOut(BaseModel):
    id: int
    vocab: list[VocabOut]
    grammar: list[GrammarOut]


class AnaBatch(BaseModel):
    cues: list[AnaOut]


class KanjiMeaning(BaseModel):
    char: str
    meaning: str = Field(description="Nghĩa tiếng Việt ngắn của chữ Hán (2–5 từ)")


class KanjiBatch(BaseModel):
    items: list[KanjiMeaning]


class LLMUnavailable(RuntimeError):
    pass


# Giá USD / 1 triệu token (bảng giá Claude API, 10/2026): input, output, cache read. Ghi cache = 1,25 × input.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}


def cost_usd(model: str, inp: int, out: int, cache_read: int = 0, cache_write: int = 0) -> float | None:
    p = PRICES.get(model)
    if not p:
        return None
    return round((inp * p[0] + out * p[1] + cache_read * p[2] + cache_write * p[0] * 1.25) / 1e6, 4)


SYSTEM_PROMPT = """Bạn là biên dịch viên phụ đề và giáo viên ngôn ngữ cho người Việt học {src}.
Với mỗi câu trong "can_xu_ly", trả về bản dịch tiếng Việt và phần phân tích.

Dịch:
- Tự nhiên như phụ đề phim Việt, ngắn gọn, đọc kịp theo tốc độ video.
- Giữ giọng nhân vật (khẩu ngữ, cộc cằn, nhõng nhẽo, kính ngữ…). Phương ngữ (vd. Kansai) → văn nói Việt suồng sã tương ứng.
- Xưng hô nhất quán theo quan hệ nhân vật và ngữ cảnh trước/sau.
- Câu gốc có nhãn người nói （チエ） → giữ nhãn ở vị trí tương ứng bằng tên Latin trong ngoặc tròn: "(Chie) Về nha.". Không tự thêm nhãn.
- Tên riêng theo BẢNG THUẬT NGỮ nếu có. "truoc"/"sau" chỉ là ngữ cảnh, không trả về.

Phân tích:
- vocab: đúng các từ trong "tu_vung" của câu (giữ nguyên lemma), nghĩa hợp ngữ cảnh, bỏ qua tên người.
- grammar: 0–2 mẫu ngữ pháp/cấu trúc đáng học nhất (kể cả khẩu ngữ, phương ngữ); câu quá đơn giản thì để trống.
- Trả về đủ mọi id trong "can_xu_ly", đúng thứ tự.
- Video tiếng Anh: "jlpt" ghi cấp CEFR (A1–C2); nghĩa từ vựng theo ngữ cảnh (phrasal verb, thành ngữ thì giải thích cả cụm trong grammar)."""

KANJI_PROMPT = """Cho danh sách chữ Hán (kèm âm Hán Việt và nghĩa tiếng Anh từ KANJIDIC2).
Trả về nghĩa tiếng Việt ngắn gọn (2–5 từ) thường gặp nhất của từng chữ, theo cách người Việt học tiếng Nhật hiểu."""


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
        self.usage = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "calls": 0}
        self.usage_by_model: dict[str, dict] = {}
        self.split = LLM_ANALYSIS_MODEL != LLM_MODEL
        self._ulock = threading.Lock()
        self.system = SYSTEM_PROMPT.format(src=LANG_NAMES.get(src_lang, src_lang))
        if target != "vi":
            self.system += f"\nNgôn ngữ đích: {LANG_NAMES.get(target, target)} (thay cho tiếng Việt)."
        if glossary.strip():
            self.system += "\n\nBẢNG THUẬT NGỮ / GHI CHÚ SERIES:\n" + glossary.strip()

    # ---------------------------------------------------------------- gọi API
    def _parse(self, system: str, content: str, fmt, max_tokens: int = 16000, model: str = LLM_MODEL,
               effort: str | None = None):
        a = self.anthropic
        kw = {}
        if not model.startswith("claude-haiku"):
            # tự chuyển model khác nếu bị bộ lọc an toàn từ chối (Haiku không hỗ trợ fallback phía server)
            kw = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        try:
            resp = self.client.beta.messages.parse(
                model=model,
                max_tokens=max_tokens,   # non-streaming: giữ ≤16k để tránh timeout HTTP
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": content}],
                output_format=fmt,
                output_config={"effort": effort or LLM_EFFORT},
                **kw,
            )
        except a.AuthenticationError as e:
            raise LLMUnavailable(f"Sai/thiếu API key: {e}") from e
        except a.PermissionDeniedError as e:
            raise LLMUnavailable(f"Không có quyền dùng model {LLM_MODEL}: {e}") from e
        except TypeError as e:   # SDK không tìm thấy API key / profile
            if "authentication" in str(e).lower():
                raise LLMUnavailable("chưa có ANTHROPIC_API_KEY") from e
            raise
        u = resp.usage
        with self._ulock:
            for bucket in (self.usage, self.usage_by_model.setdefault(model, {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "calls": 0})):
                bucket["input"] += u.input_tokens or 0
                bucket["output"] += u.output_tokens or 0
                bucket["cacheRead"] += getattr(u, "cache_read_input_tokens", 0) or 0
                bucket["cacheWrite"] += getattr(u, "cache_creation_input_tokens", 0) or 0
                bucket["calls"] += 1
        if resp.stop_reason == "refusal":
            raise RuntimeError("Model từ chối xử lý lô này")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("Đầu ra bị cắt (max_tokens) – giảm LLM_BATCH_SIZE")
        if resp.parsed_output is None:
            raise RuntimeError("Không đọc được JSON trả về")
        return resp.parsed_output

    def _call(self, payload: dict) -> BatchOut:
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if not getattr(self, "split", False):
            return self._parse(self.system, content, BatchOut)
        # tách: dịch bằng LLM_MODEL, phân tích bằng LLM_ANALYSIS_MODEL (rẻ hơn), chạy song song
        with ThreadPoolExecutor(max_workers=2) as ex:
            ft = ex.submit(self._parse, self.system + "\nCHỈ trả bản dịch (bỏ qua phần phân tích).", content, TransBatch)
            fa = ex.submit(self._parse, self.system + "\nCHỈ trả phần phân tích vocab/grammar (bỏ qua bản dịch).",
                           content, AnaBatch, 16000, LLM_ANALYSIS_MODEL)
            tr, an = ft.result(), fa.result()
        ana = {x.id: x for x in an.cues}
        return BatchOut(cues=[CueOut(id=t.id, translation=t.translation,
                                     vocab=ana[t.id].vocab if t.id in ana else [],
                                     grammar=ana[t.id].grammar if t.id in ana else []) for t in tr.cues])

    def usage_summary(self) -> dict:
        u = getattr(self, "usage", None) or {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "calls": 0}
        per = getattr(self, "usage_by_model", {}) or {LLM_MODEL: u}
        cost = sum(cost_usd(m, x["input"], x["output"], x["cacheRead"], x["cacheWrite"]) or 0 for m, x in per.items())
        return {**u, "model": LLM_MODEL, "analysisModel": LLM_ANALYSIS_MODEL, "byModel": per, "costUsd": round(cost, 4)}

    # ---------------------------------------------------------------- payload
    @staticmethod
    def build_payload(cues: list[dict], batch: list[dict], index: dict) -> dict:
        first, last = index[batch[0]["id"]], index[batch[-1]["id"]]
        before = [c for c in cues[max(0, first - LLM_CONTEXT_BEFORE * 2):first] if c["type"] == "speech"][-LLM_CONTEXT_BEFORE:]
        after = [c for c in cues[last + 1:last + 1 + LLM_CONTEXT_AFTER * 2] if c["type"] == "speech"][:LLM_CONTEXT_AFTER]
        def line(c):
            return f"{c.get('speaker') or ''}: {c['text']}" if c.get("speaker") else c["text"]
        return {
            "truoc": [line(c) for c in before],
            "can_xu_ly": [{"id": c["id"], "noi": c.get("speaker") or "", "goc": c["text"],
                           "tu_vung": [v["lemma"] for v in c.get("_cand", [])]} for c in batch],
            "sau": [line(c) for c in after],
        }

    # ---------------------------------------------------------------- xử lý
    def process(self, cues: list[dict], progress: Callable[[float], None] | None = None,
                only_ids: set[int] | None = None) -> list[str]:
        """Điền translation/vocab/grammar (+ nghĩa kanji) vào các cue speech. Trả về danh sách cảnh báo."""
        warnings: list[str] = []
        speech = [c for c in cues if c["type"] == "speech" and (only_ids is None or c["id"] in only_ids)]
        index = {c["id"]: i for i, c in enumerate(cues)}
        batches = [speech[i:i + LLM_BATCH_SIZE] for i in range(0, len(speech), LLM_BATCH_SIZE)]
        done = [0]
        lock = threading.Lock()

        def run(bi_batch):
            bi, batch = bi_batch
            payload = self.build_payload(cues, batch, index)
            result, err = None, None
            for attempt in range(2):
                try:
                    result = self._call(payload)
                    break
                except LLMUnavailable:
                    raise
                except Exception as e:  # lỗi tạm thời / JSON hỏng → thử lại 1 lần
                    log.warning("Lô %d lỗi (lần %d): %s", bi, attempt + 1, e)
                    err = e
            with lock:
                if result is None:
                    warnings.append(f"Lô {bi + 1}: {err}")
                else:
                    by_id = {o.id: o for o in result.cues}
                    missing = [c["id"] for c in batch if c["id"] not in by_id]
                    if missing:
                        warnings.append(f"Lô {bi + 1}: thiếu kết quả cho cue {missing}")
                    for c in batch:
                        if c["id"] in by_id:
                            _merge(c, by_id[c["id"]])
                done[0] += 1
                if progress:
                    progress(0.9 * done[0] / max(1, len(batches)))

        with ThreadPoolExecutor(max_workers=max(1, LLM_CONCURRENCY)) as ex:
            list(ex.map(run, enumerate(batches)))

        # nghĩa tiếng Việt cho kanji chưa có trong cache (1 lần cho mọi tập)
        try:
            chars = sorted({k["char"] for c in speech for k in c.get("kanji", [])})
            kanjidic.ensure_vi_meanings(chars, self._kanji_meanings)
            for c in speech:
                c["kanji"] = kanjidic.lookup_many([k["char"] for k in c.get("kanji", [])])
        except LLMUnavailable:
            raise
        except Exception as e:
            warnings.append(f"Nghĩa kanji: {e}")
        if progress:
            progress(1.0)
        return warnings

    def _kanji_meanings(self, chars: list[str]) -> dict[str, str]:
        out = {}
        for i in range(0, len(chars), 150):
            part = chars[i:i + 150]
            items = [{"c": ch, "hv": kanjidic.han_viet(ch), "en": kanjidic.english(ch)} for ch in part]
            res = self._parse(KANJI_PROMPT, json.dumps(items, ensure_ascii=False, separators=(",", ":")), KanjiBatch, 8000,
                              LLM_ANALYSIS_MODEL)
            out.update({it.char: it.meaning.strip() for it in res.items if it.char in part})
        return out


def _merge(cue: dict, o: CueOut) -> None:
    cue["translation"] = o.translation.strip()
    cand = {v["lemma"]: v for v in cue.get("_cand", [])}
    vocab = []
    for v in o.vocab:
        base = cand.get(v.lemma, {})
        vocab.append({"lemma": v.lemma, "reading": base.get("reading", ""), "pos": base.get("pos", ""),
                      "meaning": v.meaning, "jlpt": v.jlpt or None})
    got = {v["lemma"] for v in vocab}
    vocab += [{**b, "meaning": "", "jlpt": None} for k, b in cand.items() if k not in got]   # LLM bỏ sót vẫn giữ
    cue["vocab"] = vocab
    cue["grammar"] = [g.model_dump() for g in o.grammar]
