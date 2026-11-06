"""Ước tính chi phí LLM cho một tập ~50 phút (P1-5) khi CHƯA có API key.

    python scripts/bench/estimate_cost.py <transcript.json>      (vd. transcript tạo từ data/bench/long50.wav)

Cách tính:
- Input: dựng ĐÚNG payload mà Translator gửi (system prompt + JSON từng lô), đếm token gần đúng.
- Output: mô phỏng JSON trả về cho mỗi câu theo mẫu demo_fixture.json (bản dịch + nghĩa từ vựng + ngữ pháp).
- Token ≈ ký tự CJK × 1,0 + ký tự Việt có dấu × 0,5 + ký tự ASCII ÷ 3,5 (sai số ±30 %; khi có API key
  dùng số đo thật trong doc["stats"]["llmUsage"] hoặc client.messages.count_tokens).
- Thinking (Opus/Sonnet 5.5 luôn bật adaptive thinking, tính như output): giả định thêm 0 %–50 % output
  với effort=low, 30 %–100 % với medium.
So sánh: thiết kế ban đầu (kanji do LLM sinh, JSON thụt lề, gửi lại bản dịch trước làm ngữ cảnh)
và bản tối ưu (kanji từ KANJIDIC2, JSON gọn, cache system prompt).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.pipeline import build  # noqa: E402
from app.pipeline.translate import PRICES, SYSTEM_PROMPT, Translator  # noqa: E402

CJK = re.compile(r"[぀-ヿ㐀-鿿＀-￯]")
VI = re.compile(r"[À-ỹĐđ]")


def tokens(s: str) -> float:
    cjk = len(CJK.findall(s))
    vi = len(VI.findall(s))
    other = len(s) - cjk - vi
    return cjk * 1.0 + vi * 0.5 + other / 3.5


def main(doc_path: str):
    doc = json.loads(Path(doc_path).read_text(encoding="utf-8"))
    cues = doc["cues"]
    for c in cues:
        c.pop("vocab", None), c.pop("kanji", None)
        build.enrich_cue(c, "ja")
    speech = [c for c in cues if c["type"] == "speech"]
    fx = json.loads((ROOT / "scripts" / "demo_fixture.json").read_text(encoding="utf-8"))
    # mẫu đầu ra trung bình / câu từ fixture (9 câu có dịch + phân tích đầy đủ)
    tr = list(fx["translations"].values())
    avg_tr = sum(tokens(t) for t in tr) / len(tr)
    avg_vocab = sum(tokens(json.dumps({"lemma": k, "meaning": v[0], "jlpt": v[1]}, ensure_ascii=False)) for k, v in fx["vocab"].items()) / len(fx["vocab"])
    g_all = [g for gs in fx["grammar"].values() for g in gs]
    avg_gram = sum(tokens(json.dumps({"pattern": g[0], "meaning": g[1], "explanation": g[2], "jlpt": g[3]}, ensure_ascii=False)) for g in g_all) / len(g_all)
    avg_kanji_llm = sum(tokens(json.dumps({"char": k, "on": v[0], "kun": v[1], "hanViet": v[2], "meaning": v[3]}, ensure_ascii=False)) for k, v in fx["kanji"].items()) / len(fx["kanji"])
    n_vocab = sum(len(c["_cand"]) for c in speech)
    n_kanji = sum(len(c["_kanji"]) for c in speech)
    uniq_kanji = len({k for c in speech for k in c["_kanji"]})
    n_gram = 1.0 * len(speech)                       # ~1 mẫu ngữ pháp / câu (0–2)
    batch = 30
    index = {c["id"]: i for i, c in enumerate(cues)}
    batches = [speech[i:i + batch] for i in range(0, len(speech), batch)]
    sys_tok = tokens(SYSTEM_PROMPT) + 150             # + bảng thuật ngữ
    # --- tối ưu
    inp_opt = sum(tokens(json.dumps(Translator.build_payload(cues, b, index), ensure_ascii=False, separators=(",", ":"))) for b in batches)
    out_opt = len(speech) * (avg_tr + 12) + n_vocab * avg_vocab + n_gram * avg_gram + len(batches) * 10
    kanji_call_in, kanji_call_out = uniq_kanji * 12, uniq_kanji * 8     # 1 lần cho kanji chưa có trong cache
    # --- ban đầu
    def payload_old(b):
        p = Translator.build_payload(cues, b, index)
        for item, c in zip(p["can_xu_ly"], b):
            item["kanji"] = c["_kanji"]
        p["truoc"] = [{"goc": x, "dich": "x" * 40} for x in p["truoc"]]
        return json.dumps(p, ensure_ascii=False, indent=1)
    inp_old = sum(tokens(payload_old(b)) for b in batches)
    out_old = out_opt + n_vocab * 6 + n_kanji * avg_kanji_llm             # + reading từ vựng + kanji
    rows = []
    for model, (pi, po, pc) in PRICES.items():
        for name, inp, out, extra_in, extra_out, sys_cached in (
                ("ban đầu", inp_old, out_old, 0, 0, False),
                ("tối ưu", inp_opt, out_opt, kanji_call_in, kanji_call_out, True)):
            for effort, (tlo, thi) in (("low", (0.0, 0.5)), ("medium", (0.3, 1.0))):
                sys_cost = (sys_tok * pi * 1.25 + sys_tok * (len(batches) - 1) * pc) if sys_cached else sys_tok * len(batches) * pi
                base_in = (inp + extra_in) * pi + sys_cost
                lo = (base_in + (out + extra_out) * (1 + tlo) * po) / 1e6
                hi = (base_in * 1.3 + (out + extra_out) * 1.3 * (1 + thi) * po) / 1e6
                rows.append((model, name, effort, round(lo, 3), round(hi, 3)))
    # cấu hình tách: dịch bằng model A, phân tích bằng model B (mỗi lô gửi cùng payload cho 2 model)
    out_tr = len(speech) * (avg_tr + 12) + len(batches) * 10
    out_an = out_opt - out_tr
    for ma, mb in (("claude-opus-5-5", "claude-haiku-5-5"), ("claude-sonnet-5-5", "claude-haiku-5-5")):
        pa, pb = PRICES[ma], PRICES[mb]
        for effort, (tlo, thi) in (("low", (0.0, 0.5)), ("medium", (0.3, 1.0))):
            sys_a = sys_tok * pa[0] * 1.25 + sys_tok * (len(batches) - 1) * pa[2]
            sys_b = sys_tok * pb[0] * 1.25 + sys_tok * (len(batches) - 1) * pb[2]
            in_cost = inp_opt * (pa[0] + pb[0]) + sys_a + sys_b + kanji_call_in * pb[0]
            lo = (in_cost + out_tr * (1 + tlo) * pa[1] + (out_an + kanji_call_out) * (1 + tlo) * pb[1]) / 1e6
            hi = (in_cost * 1.3 + 1.3 * (out_tr * (1 + thi) * pa[1] + (out_an + kanji_call_out) * (1 + thi) * pb[1])) / 1e6
            rows.append((f"{ma.split('-')[1]}+{mb.split('-')[1]}", "tách", effort, round(lo, 3), round(hi, 3)))
    info = {"audioMin": round((doc.get("duration") or 0) / 60, 1), "speechCues": len(speech), "batches": len(batches),
            "vocabItems": n_vocab, "kanjiOccurrences": n_kanji, "uniqueKanji": uniq_kanji,
            "inputTokensOpt": round(inp_opt), "outputTokensOpt": round(out_opt),
            "inputTokensOld": round(inp_old), "outputTokensOld": round(out_old)}
    print(json.dumps(info, ensure_ascii=False))
    print(f"{'model':18} {'cấu hình':9} {'effort':7} USD/tập (thấp–cao)")
    for r in rows:
        print(f"{r[0]:18} {r[1]:9} {r[2]:7} {r[3]:.2f} – {r[4]:.2f}")
    out = ROOT / "data" / "bench" / "results" / "cost_estimate.json"
    out.write_text(json.dumps({"info": info, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
