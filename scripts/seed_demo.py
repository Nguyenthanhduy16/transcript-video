"""Nạp video demo vào data/ bằng pipeline thật; bước LLM được thay bằng demo_fixture.json.

    cd backend && python ../scripts/seed_demo.py
(Có ANTHROPIC_API_KEY thì chạy với --real để dùng Claude thật.)
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.pipeline import run, source                       # noqa: E402
from app.pipeline.translate import BatchOut, Translator     # noqa: E402

DEMO = ROOT / "data" / "demo"
if not (DEMO / "demo.mp4").exists():
    import runpy
    runpy.run_path(str(ROOT / "scripts" / "make_demo.py"))

fx = json.loads((ROOT / "scripts" / "demo_fixture.json").read_text(encoding="utf-8"))


def fake_call(self, payload):
    out = []
    for c in payload["CAN_XU_LY"]:
        text = c["goc"]
        out.append({
            "id": c["id"],
            "translation": fx["translations"].get(text, ""),
            "vocab": [{"lemma": l, "reading": "", "meaning": fx["vocab"][l][0], "jlpt": fx["vocab"][l][1]}
                      for l in c["ung_vien_tu_vung"] if l in fx["vocab"]],
            "kanji": [{"char": k, "on": fx["kanji"][k][0], "kun": fx["kanji"][k][1],
                       "hanViet": fx["kanji"][k][2], "meaning": fx["kanji"][k][3]}
                      for k in c["kanji"] if k in fx["kanji"]],
            "grammar": [{"pattern": g[0], "meaning": g[1], "explanation": g[2], "jlpt": g[3]}
                        for g in fx["grammar"].get(text, [])],
        })
    return BatchOut.model_validate({"cues": out})


if "--real" not in sys.argv:
    Translator.__init__ = lambda self, *a, **k: setattr(self, "system", "")  # không cần API key
    Translator._call = fake_call

video_id = "demo-kansai-01"
mdir = source.media_dir(video_id)
shutil.copy(DEMO / "demo.mp4", mdir / "video.mp4")
shutil.copy(DEMO / "demo_ja.srt", mdir / "original.srt")
doc = run.run_pipeline({
    "video_id": video_id, "upload_path": str(mdir / "video.mp4"), "original_name": "demo.mp4",
    "subtitle_path": str(mdir / "original.srt"), "title": "Tan học (demo)", "series": "Demo Kansai",
    "episode": 1, "lang": "ja", "target": "vi",
    "glossary": "ハル=Haru, ソウタ=Sota, マサキ=Masaki, 先生=Cô giáo. Trẻ con nói giọng Kansai.",
}, lambda stage, pct, msg: print(f"[{pct:5.1f}%] {stage}: {msg}"))
print("Đã tạo:", doc["videoId"], len(doc["cues"]), "cue;", "cảnh báo:", doc["warnings"])
