"""Kiểm thử các bước không cần mạng/GPU: chia cue, phân loại, furigana, romaji, dịch (mock LLM), API."""
import os
import sys
from pathlib import Path

import pytest

os.environ["DATA_DIR"] = str(Path(__file__).parent / "_data")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import japanese as ja                 # noqa: E402
from app.pipeline.build import enrich_cue, normalize_cues  # noqa: E402
from app.pipeline.cues import classify, cues_from_words, split_long_cue, split_speaker  # noqa: E402
from app.pipeline.subtitles import parse_subtitle_file  # noqa: E402
from app.pipeline.translate import BatchOut, Translator  # noqa: E402


@pytest.mark.parametrize("text,kind", [
    ("♪～", "music"), ("～♪", "music"), ("♪ 夢を見ていた ♪", "music"),
    ("（チャイム）", "sfx"), ("（笑い声）", "sfx"), ("[拍手]", "sfx"),
    ("（チエ）さいなら", "speech"), ("分かってるわい", "speech"),
])
def test_classify(text, kind):
    assert classify(text) == kind


def test_split_speaker():
    assert split_speaker("（マサル）へへへッ…") == ("マサル", "へへへッ…", False)
    sp, text, multi = split_speaker("（チエ）さいなら（ヒラメ）さいなら")
    assert sp == "チエ" and multi and "（ヒラメ）" in text
    assert split_speaker("こんにちは") == (None, "こんにちは", False)


def test_furigana_okurigana():
    assert ja.furigana_segments("忘れ", "わすれ") == [["忘", "わす"], ["れ", None]]
    assert ja.furigana_segments("宿題", "しゅくだい") == [["宿題", "しゅくだい"]]
    assert ja.furigana_segments("お金", "おかね") == [["お", None], ["金", "かね"]]
    assert ja.furigana_segments("ひらがな", "ひらがな") == [["ひらがな", None]]


def test_romaji():
    assert ja.to_romaji("しゅくだい") == "shukudai"
    assert ja.to_romaji("ちょっと") == "chotto"
    assert ja.to_romaji("こんいん") == "kon'in"
    assert ja.to_romaji("ラーメン") == "raamen"
    assert ja.romaji_line(ja.tokenize("東京へ行きました。")) == "toukyou e ikimashita."


def test_tokenize_keeps_speaker_tag_and_vocab():
    toks = ja.tokenize("（チエ）宿題を忘れた")
    assert toks[0]["pos"] == "speaker"
    lemmas = [v["lemma"] for v in ja.vocab_candidates(toks)]
    assert "宿題" in lemmas and "忘れる" in lemmas
    assert ja.extract_kanji("宿題を忘れた") == ["宿", "題", "忘"]


def test_cues_from_words_respects_limits():
    words, t = [], 0.0
    for i in range(40):
        w = "あいうえお。" if i % 6 == 5 else "あいう"
        words.append({"start": t, "end": t + 0.4, "word": w})
        t += 0.45
    cues = cues_from_words(words)
    assert all(c["end"] - c["start"] <= 7.0 + 1e-6 for c in cues)
    assert all(len(c["text"]) <= 32 for c in cues)
    assert "".join(c["text"] for c in cues) == "".join(w["word"] for w in words)


def test_split_long_cue():
    c = {"start": 0, "end": 12, "text": "今日はいい天気ですね。散歩に行きませんか。それとも家でゆっくりしますか。"}
    parts = split_long_cue(c)
    assert len(parts) >= 2 and parts[0]["start"] == 0 and parts[-1]["end"] == 12


def test_parse_srt_and_normalize(tmp_path):
    p = tmp_path / "a.srt"
    p.write_text("1\n00:00:01,000 --> 00:00:03,000\n<i>♪～</i>\n\n2\n00:00:04,000 --> 00:00:04,300\n"
                 "（チエ）分かってるわい\n\n", encoding="utf-8")
    cues = normalize_cues(parse_subtitle_file(p), "ja")
    assert [c["type"] for c in cues] == ["music", "speech"]
    assert cues[1]["speaker"] == "チエ" and cues[1]["text"] == "分かってるわい"
    assert cues[1]["end"] - cues[1]["start"] >= 1.0      # kéo dài cue quá ngắn


def test_translator_merge_with_mock():
    cues = normalize_cues([{"start": 0, "end": 2, "text": "（チエ）宿題を忘れた"},
                           {"start": 2, "end": 4, "text": "（チャイム）"}], "ja")
    for c in cues:
        enrich_cue(c, "ja")
    seen = {}

    def fake_call(self, payload):
        seen.update(payload)
        return BatchOut.model_validate({"cues": [{
            "id": 1, "translation": "Quên bài tập rồi.",
            "vocab": [{"lemma": "宿題", "reading": "しゅくだい", "meaning": "bài tập về nhà", "jlpt": "N5"}],
            "kanji": [{"char": "宿", "on": ["シュク"], "kun": ["やど"], "hanViet": "TÚC", "meaning": "trọ"}],
            "grammar": []}]})

    tr = Translator.__new__(Translator)
    tr._call = fake_call.__get__(tr)
    warns = tr.process(cues)
    assert [c["id"] for c in seen["CAN_XU_LY"]] == [1]          # cue tiếng động không gửi đi dịch
    assert cues[0]["translation"] == "Quên bài tập rồi."
    v = {x["lemma"]: x for x in cues[0]["vocab"]}
    assert v["宿題"]["meaning"] == "bài tập về nhà"
    assert "忘れる" in v and v["忘れる"]["meaning"] == ""          # từ LLM bỏ sót vẫn giữ
    assert cues[1]["translation"] == "" and cues[1]["vocab"] == []
    assert warns == []


def test_api_upload_flow(tmp_path):
    from fastapi.testclient import TestClient
    import subprocess
    import time
    from app.main import app

    vid = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x36:d=5",
                    "-f", "lavfi", "-i", "sine=d=5", "-shortest", str(vid)], check=True)
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:02,500\n（ハル）ほんまに？\n\n", encoding="utf-8")
    os.environ["LLM_PROVIDER"] = "none"
    import app.pipeline.translate as t
    t.LLM_PROVIDER = "none"
    c = TestClient(app)
    r = c.post("/api/jobs/upload", files={"video": ("v.mp4", vid.read_bytes()), "subtitle": ("s.srt", srt.read_bytes())},
               data={"series": "T", "episode": "1"})
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    for _ in range(50):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert j["status"] == "done", j
    assert any("LLM" in w for w in j["warnings"])
    doc = c.get(f"/api/videos/{j['videoId']}").json()
    assert doc["cues"][0]["speaker"] == "ハル" and doc["player"]["type"] == "html5"
    # sửa câu → tách từ lại, đánh dấu cần phân tích
    cue = doc["cues"][0]
    r = c.put(f"/api/videos/{j['videoId']}", json={"cues": [{**{k: cue[k] for k in ("id", "start", "end", "speaker", "type")},
                                                             "text": "本当に？", "translation": "Thật không?"}]})
    d2 = r.json()
    assert d2["cues"][0]["tokens"][0]["surface"] == "本当" and d2["needsAnalysis"] == [cue["id"]]
    srt_out = c.get(f"/api/videos/{j['videoId']}/export.srt").text
    assert "00:00:00,500 --> 00:00:02,500" in srt_out and "Thật không?" in srt_out
    c.delete(f"/api/videos/{j['videoId']}")
