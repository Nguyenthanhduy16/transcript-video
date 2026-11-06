"""Chấm ASR + chia câu + người nói trên bộ benchmark (data/bench).

    python scripts/bench/eval_asr.py --engines reazon whisper-onnx --files news anime variety
    python scripts/bench/eval_asr.py --engines reazon --files long50

Chỉ số:
- CER chữ   : khoảng cách sửa ký tự / số ký tự đáp án, sau khi chuẩn hoá NFKC và bỏ dấu câu, khoảng trắng.
- CER đọc   : như trên nhưng so cách đọc hiragana (SudachiPy) – không phạt 分かる/わかる, 七/7.
- Lệch thời gian: với mỗi câu đáp án, |Δ đầu| = khoảng cách từ mốc đầu câu tới mốc đầu cue gần nhất,
  |Δ cuối| tương tự. Câu "khớp" khi cả hai ≤ 300 ms.
- Người nói: mỗi câu đáp án lấy người nói của cue chồng lấn nhiều nhất; ghép nhãn máy ↔ nhãn đáp án
  tối ưu (Hungarian) rồi tính tỉ lệ đúng. Chạy 2 chế độ: tự đoán số người / biết trước số người.
- Tốc độ: thời gian xử lý, RTF = thời gian xử lý / thời lượng audio.
Kết quả ghi ra data/bench/results/<file>__<engine>.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
BENCH = ROOT / "data" / "bench"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    return re.sub(r"[\s、。，．,.!?！？「」『』…・~〜ー―\-]", "", s)


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    # tính theo đoạn ~2000 ký tự để không tốn O(n²) bộ nhớ với file dài
    ref, hyp = norm(ref), norm(hyp)
    if len(ref) <= 3000:
        return edit_distance(ref, hyp) / max(1, len(ref))
    raise ValueError("dùng cer_lines cho văn bản dài")


def reading(s: str) -> str:
    from app.pipeline import japanese as ja
    return "".join(t["reading"] or t["surface"] for t in ja.tokenize(norm(s)) if t["pos"] not in ("symbol", "space"))


def align_text_per_line(gt, cues):
    """Gán văn bản máy cho từng câu đáp án theo thời gian (tâm cue nằm trong câu) → CER ghép theo câu."""
    out = {i: "" for i in range(len(gt))}
    starts = [g["start"] for g in gt]
    import bisect
    for c in cues:
        mid = (c["start"] + c["end"]) / 2
        k = bisect.bisect_right(starts, mid)
        cand = [i for i in (k - 1, k) if 0 <= i < len(gt)]
        best = min(cand, key=lambda i: 0 if gt[i]["start"] - 0.3 <= mid <= gt[i]["end"] + 0.3
                   else min(abs(mid - gt[i]["start"]), abs(mid - gt[i]["end"])))
        out[best] += c["text"]
    return out


def timing(gt, cues, tol=0.3):
    starts = np.array([c["start"] for c in cues])
    ends = np.array([c["end"] for c in cues])
    ok = ok_start = 0
    ds, de = [], []
    for g in gt:
        d1 = float(np.min(np.abs(starts - g["start"])))
        d2 = float(np.min(np.abs(ends - g["end"])))
        ds.append(d1)
        de.append(d2)
        ok_start += d1 <= tol
        ok += d1 <= tol and d2 <= tol
    return {"lines": len(gt), "okBothPct": round(100 * ok / len(gt), 1), "okStartPct": round(100 * ok_start / len(gt), 1),
            "medianStartMs": round(1000 * float(np.median(ds))), "p90StartMs": round(1000 * float(np.percentile(ds, 90))),
            "medianEndMs": round(1000 * float(np.median(de))), "p90EndMs": round(1000 * float(np.percentile(de, 90)))}


def speaker_acc(gt, cues):
    from scipy.optimize import linear_sum_assignment
    hyp_lab = []
    for g in gt:
        best, ov = None, 0.0
        for c in cues:
            o = min(g["end"], c["end"]) - max(g["start"], c["start"])
            if o > ov:
                best, ov = c.get("speaker"), o
        hyp_lab.append(best)
    G = sorted({g["speaker"] for g in gt})
    H = sorted({h for h in hyp_lab if h}, key=str)
    if not H:
        return {"accPct": 0.0, "found": 0, "truth": len(G)}
    M = np.zeros((len(H), len(G)))
    for h, g in zip(hyp_lab, gt):
        if h:
            M[H.index(h), G.index(g["speaker"])] += 1
    r, c = linear_sum_assignment(-M)
    return {"accPct": round(100 * M[r, c].sum() / len(gt), 1), "found": len(H), "truth": len(G)}


def run(file: str, engine: str, diar: bool = True) -> dict:
    os.environ["ASR_ENGINE"] = engine
    import importlib
    from app import config
    importlib.reload(config)
    from app.pipeline import asr, build, cues as cuesmod, diarize
    importlib.reload(asr)
    meta = json.loads((BENCH / f"{file}.gt.json").read_text(encoding="utf-8"))
    gt = meta["lines"]
    wav = str(BENCH / f"{file}.wav")
    t0 = time.time()
    res = asr.transcribe(wav, "ja")
    t_asr = time.time() - t0
    raw = cuesmod.cues_from_asr(res["segments"])
    cues = build.normalize_cues(raw, "ja")
    t1 = time.time()
    for c in cues:
        build.enrich_cue(c, "ja")
    t_nlp = time.time() - t1
    out = {"file": file, "engine": res["engine"], "condition": meta["condition"], "audioSec": meta["durationSec"],
           "cues": len(cues), "gtLines": len(gt), "asrSec": round(t_asr, 2), "nlpSec": round(t_nlp, 2),
           "rtf": round(t_asr / meta["durationSec"], 4)}
    # CER
    per_line = align_text_per_line(gt, cues)
    errs = chars = errs_r = chars_r = 0
    for i, g in enumerate(gt):
        ref, hyp = norm(g["text"]), norm(per_line[i])
        errs += edit_distance(ref, hyp)
        chars += len(ref)
        rr, rh = reading(g["text"]), reading(per_line[i])
        errs_r += edit_distance(rr, rh)
        chars_r += len(rr)
    out["cerPct"] = round(100 * errs / chars, 2)
    out["cerReadingPct"] = round(100 * errs_r / chars_r, 2)
    out["timing"] = timing(gt, cues)
    if diar:
        audio = asr.load_wav(wav)
        for mode_name, n in (("auto", None), ("known", len(meta["speakers"]))):
            for c in cues:
                c["speaker"] = None
            t2 = time.time()
            diarize.assign_by_embedding(cues, audio, n)
            out[f"speaker_{mode_name}"] = {**speaker_acc(gt, cues), "sec": round(time.time() - t2, 2)}
    out["samples"] = [{"gt": g["text"], "hyp": per_line[i]} for i, g in enumerate(gt[:6])]
    return out


def score_doc(file: str, doc_path: str) -> dict:
    """Chấm một transcript đã tạo bởi pipeline đầy đủ (run_pipeline) – không chạy lại ASR."""
    meta = json.loads((BENCH / f"{file}.gt.json").read_text(encoding="utf-8"))
    gt = meta["lines"]
    doc = json.loads(Path(doc_path).read_text(encoding="utf-8"))
    cues = [c for c in doc["cues"] if c["type"] == "speech"]
    per_line = align_text_per_line(gt, cues)
    errs = chars = errs_r = chars_r = 0
    for i, g in enumerate(gt):
        errs += edit_distance(norm(g["text"]), norm(per_line[i])); chars += len(norm(g["text"]))
        rr = reading(g["text"]); errs_r += edit_distance(rr, reading(per_line[i])); chars_r += len(rr)
    return {"file": file, "audioSec": meta["durationSec"], "cues": len(doc["cues"]), "gtLines": len(gt),
            "cerPct": round(100 * errs / chars, 2), "cerReadingPct": round(100 * errs_r / chars_r, 2),
            "timing": timing(gt, doc["cues"]), "speaker_auto": speaker_acc(gt, doc["cues"]), "stats": doc.get("stats")}


def main():
    if "--score-doc" in sys.argv:
        f, path = sys.argv[sys.argv.index("--score-doc") + 1:sys.argv.index("--score-doc") + 3]
        r = score_doc(f, path)
        (BENCH / "results").mkdir(exist_ok=True)
        (BENCH / "results" / f"{f}__pipeline.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({k: v for k, v in r.items() if k != "stats"}, ensure_ascii=False), "\nstats:", r["stats"])
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--engines", nargs="+", default=["reazon"])
    ap.add_argument("--files", nargs="+", default=["news", "anime", "variety"])
    ap.add_argument("--no-diar", action="store_true")
    a = ap.parse_args()
    (BENCH / "results").mkdir(exist_ok=True)
    for f in a.files:
        for e in a.engines:
            r = run(f, e, diar=not a.no_diar)
            (BENCH / "results" / f"{f}__{e}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
            sp = r.get("speaker_auto", {}), r.get("speaker_known", {})
            print(f"{f:8} {e:13} CER {r['cerPct']:5.2f}% (đọc {r['cerReadingPct']:5.2f}%) | khớp ±300ms {r['timing']['okBothPct']:5.1f}% "
                  f"(đầu {r['timing']['okStartPct']}%) | ASR {r['asrSec']}s RTF {r['rtf']} | người nói auto {sp[0].get('accPct')}% "
                  f"({sp[0].get('found')}/{sp[0].get('truth')}) biết số {sp[1].get('accPct')}%")


if __name__ == "__main__":
    main()
