"""Phiếu chấm bản dịch cho Người 4 (tiêu chí P1-3: ≥ 70 % câu "dùng được, sửa nhẹ").

Xuất phiếu (mở bằng Excel/Google Sheets, cột "diem" điền 2 / 1 / 0):
    python scripts/bench/translation_review.py export data/videos/<videoId>.json [--sample 100]
        2 = dùng được nguyên văn, 1 = dùng được, sửa nhẹ, 0 = sai / phải dịch lại
Tính kết quả sau khi chấm:
    python scripts/bench/translation_review.py score phieu_cham_<videoId>.csv
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path


def export(doc_path: str, sample: int | None):
    doc = json.loads(Path(doc_path).read_text(encoding="utf-8"))
    rows = [c for c in doc["cues"] if c["type"] == "speech" and c.get("translation")]
    if sample and sample < len(rows):
        random.seed(13)
        rows = sorted(random.sample(rows, sample), key=lambda c: c["start"])
    out = Path(f"phieu_cham_{doc['videoId']}.csv")
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "thoi_gian", "nguoi_noi", "cau_goc", "ban_dich", "diem", "ban_sua", "ghi_chu"])
        for c in rows:
            m, s = divmod(int(c["start"]), 60)
            w.writerow([c["id"], f"{m}:{s:02d}", c.get("speaker") or "", c["text"], c["translation"], "", "", ""])
    stats = (doc.get("stats") or {}).get("llmUsage", {})
    print(f"Đã xuất {len(rows)} câu → {out}  (model: {stats.get('model')}, chi phí đo được: {stats.get('costUsd')} USD)")


def score(csv_path: str):
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["diem"].strip() in ("0", "1", "2")]
    if not rows:
        print("Chưa có câu nào được chấm (cột 'diem' = 0/1/2).")
        return
    n = len(rows)
    c2 = sum(r["diem"].strip() == "2" for r in rows)
    c1 = sum(r["diem"].strip() == "1" for r in rows)
    usable = 100 * (c1 + c2) / n
    print(f"{n} câu đã chấm: {c2} dùng nguyên văn, {c1} sửa nhẹ, {n - c1 - c2} sai → "
          f"dùng được {usable:.1f}% ({'ĐẠT' if usable >= 70 else 'CHƯA ĐẠT'} tiêu chí ≥ 70%)")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "export":
        k = sys.argv.index("--sample") if "--sample" in sys.argv else None
        export(sys.argv[2], int(sys.argv[k + 1]) if k else None)
    elif len(sys.argv) >= 3 and sys.argv[1] == "score":
        score(sys.argv[2])
    else:
        print(__doc__)
