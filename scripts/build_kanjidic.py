"""Trích bảng kanji gọn từ KANJIDIC2 (trong gói PyPI jamdict-data) → backend/app/data/kanjidic.json.gz

    pip download --no-deps jamdict-data && tar xzf jamdict_data-*.tar.gz && xz -dk .../jamdict.db.xz
    python scripts/build_kanjidic.py path/to/jamdict.db

Nguồn: KANJIDIC2 © Electronic Dictionary Research and Development Group (EDRDG), giấy phép CC BY-SA 4.0
(https://www.edrdg.org/edrdg/licence.html). Dữ liệu phái sinh phân phối cùng giấy phép.
"""
import gzip
import json
import sqlite3
import sys
from pathlib import Path

db = sqlite3.connect(sys.argv[1])
out = {}
for cid, lit, strokes, grade, freq, jlpt in db.execute("select ID, literal, stroke_count, grade, freq, jlpt from character"):
    rows = db.execute("select r_type, value from reading where gid in (select ID from rm_group where cid=?)", (cid,)).fetchall()
    mean = [m for (m,) in db.execute("select value from meaning where m_lang='' and gid in (select ID from rm_group where cid=?)", (cid,))]
    rec = {"on": [v for t, v in rows if t == "ja_on"], "kun": [v for t, v in rows if t == "ja_kun"],
           "vi": [v for t, v in rows if t == "vietnam"], "en": mean[:4]}
    if grade: rec["grade"] = grade
    if freq: rec["freq"] = freq
    if jlpt: rec["jlptOld"] = jlpt          # JLPT cũ (1–4), trước 2010
    if strokes: rec["strokes"] = strokes
    out[lit] = rec
dst = Path(__file__).resolve().parents[1] / "backend" / "app" / "data" / "kanjidic.json.gz"
with gzip.open(dst, "wt", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(len(out), "kanji →", dst, dst.stat().st_size // 1024, "KB;", sum(1 for v in out.values() if v["vi"]), "có âm Hán Việt")
