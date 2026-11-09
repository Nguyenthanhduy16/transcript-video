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
    assert cues[1]["end"] == 4.3                         # giữ đúng mốc kết thúc (không kéo dài)


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
            "vocab": [{"lemma": "宿題", "meaning": "bài tập về nhà", "jlpt": "N5"}],
            "grammar": []}]})

    tr = Translator.__new__(Translator)
    tr._call = fake_call.__get__(tr)
    tr._kanji_meanings = lambda chars: {c: "nghĩa " + c for c in chars}
    warns = tr.process(cues)
    assert [c["id"] for c in seen["can_xu_ly"]] == [1]          # cue tiếng động không gửi đi dịch
    assert cues[0]["translation"] == "Quên bài tập rồi."
    v = {x["lemma"]: x for x in cues[0]["vocab"]}
    assert v["宿題"]["meaning"] == "bài tập về nhà" and v["宿題"]["reading"] == "しゅくだい"
    k = {x["char"]: x for x in cues[0]["kanji"]}
    assert k["宿"]["hanViet"].startswith("TÚC") and "シュク" in k["宿"]["on"]      # từ KANJIDIC2
    assert k["宿"]["meaning"] == "nghĩa 宿"                                       # nghĩa VI qua cache
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


# ------------------------------------------------------------------ bổ sung cho P1-2…P1-4
@pytest.mark.parametrize("text,word,reading", [
    ("今日は四月一日です。", "一日", "ついたち"), ("二十日に来ます。", "二十日", "はつか"),
    ("みかんを八つ買った", "八つ", "やっつ"), ("三十分待って", "三十分", "さんじゅっぷん"),
    ("時間は十分です。", "十分", "じゅうぶん"), ("鉛筆を六本", "六本", "ろっぽん"),
    ("三階建て", "三階", "さんがい"), ("四人分", "四人", "よにん"), ("一年中", "一年中", "いちねんじゅう"),
    ("和菓子作り", "作り", "づくり"), ("富士山の水", "富士山", "ふじさん"), ("一昨日", "一昨日", "おととい"),
])
def test_number_and_special_readings(text, word, reading):
    toks = {t["surface"]: t["reading"] for t in ja.tokenize(text)}
    assert toks.get(word) == reading, toks


def test_merge_fragments_nearest_neighbor():
    from app.pipeline.cues import merge_fragments
    cues = [{"start": 0.0, "end": 0.6, "text": "こんばんは"}, {"start": 0.8, "end": 2.5, "text": "七時のニュースです"},
            {"start": 3.4, "end": 3.9, "text": "まず"}, {"start": 5.0, "end": 7.0, "text": "天気です"}]
    out = merge_fragments(cues)
    assert out[0]["text"] == "こんばんは七時のニュースです"      # gap 0,2 s → gộp
    assert [c["text"] for c in out[1:]] == ["まず", "天気です"]    # gap > 0,35 s → giữ riêng


def test_error_classification():
    from app.errors import classify_exception
    from app.pipeline.source import SourceError
    e = classify_exception(SourceError("Không tải được link (HTTP 404).", "SOURCE_NOT_FOUND"))
    assert e.code == "SOURCE_NOT_FOUND" and not e.retryable
    assert classify_exception(SourceError("timeout", "SOURCE_TIMEOUT", True)).retryable
    assert classify_exception(ValueError("x")).code == "INTERNAL"
    assert classify_exception(FileNotFoundError(2, "No such file or directory", "ffmpeg")).code == "FFMPEG_MISSING"


def test_kind_of_rejects_non_http():
    from app.pipeline.source import SourceError, kind_of
    with pytest.raises(SourceError) as ei:
        kind_of("ftp://example.com/a.mp4")
    assert ei.value.code == "UNSUPPORTED_URL"
    assert kind_of("https://youtu.be/abc123XYZ") == "youtube"
    assert kind_of("https://x.com/v/a.m3u8") == "media"


def test_kanjidic_lookup():
    from app.pipeline import kanji
    k = kanji.lookup("漢")
    assert k["hanViet"].startswith("HÁN") and "カン" in k["on"] and k["strokes"] == 13


def test_extension_endpoints(tmp_path):
    """/api/jobs/subtitle (phụ đề YouTube do extension gửi) + /api/resolve."""
    import time
    from fastapi.testclient import TestClient
    from app.main import app
    import app.pipeline.translate as t
    t.LLM_PROVIDER = "none"
    c = TestClient(app)
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n（ハル）宿題、忘れたらあかんで。\n\n00:00:04.000 --> 00:00:05.500\n♪～\n"
    r = c.post("/api/jobs/subtitle", json={"url": "https://www.youtube.com/watch?v=extTest0001", "subtitle": vtt, "title": "Thử"})
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    for _ in range(50):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert j["status"] == "done", j
    doc = c.get("/api/videos/extTest0001").json()
    assert doc["player"] == {"type": "youtube", "youtubeId": "extTest0001"}
    assert doc["cues"][0]["speaker"] == "ハル" and doc["cues"][1]["type"] == "music"
    res = c.get("/api/resolve", params={"url": "https://youtu.be/extTest0001"}).json()
    assert res["exists"] and res["videoId"] == "extTest0001"
    assert not c.get("/api/resolve", params={"url": "https://example.com/khac.mp4"}).json()["exists"]
    assert c.post("/api/jobs/subtitle", json={"url": "ftp://x", "subtitle": vtt}).status_code == 400
    c.delete("/api/videos/extTest0001")


def test_english_tokens_and_cues():
    from app.pipeline import english as en
    from app.pipeline.cues import cues_from_asr, split_long_cue
    from app.config import max_chars_for
    t = en.tokenize("That's impressive. We're getting better at learning languages!")
    assert "".join(x["surface"] for x in t) == "That's impressive. We're getting better at learning languages!"
    assert [v["lemma"] for v in en.vocab_candidates(t)] == ["impressive", "good", "learn", "language"]
    assert max_chars_for("en") > max_chars_for("ja")
    # tiếng Anh nối từ có dấu cách, tiếng Nhật nối liền
    segs = [{"start": 0.0, "end": 0.5, "text": "Hello", "words": []}, {"start": 0.6, "end": 2.0, "text": "world again", "words": []}]
    assert cues_from_asr(segs, max_chars_for("en"))[0]["text"] == "Hello world again"
    ja = [{"start": 0.0, "end": 0.5, "text": "こんばんは", "words": []}, {"start": 0.6, "end": 2.0, "text": "七時です", "words": []}]
    assert cues_from_asr(ja, max_chars_for("ja"))[0]["text"] == "こんばんは七時です"
    long = {"start": 0, "end": 12, "text": "This is the first sentence of a long talk. And this is the second one, which goes on for a while."}
    parts = split_long_cue(long, max_chars_for("en"))
    assert len(parts) == 2 and parts[1]["text"].startswith("And")


def test_translate_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.pipeline import quick_translate as qt
    from app.pipeline.translate import Translator
    calls = []

    def fake_init(self, *a, **k):
        self.usage = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "calls": 0}

    def fake_parse(self, system, content, fmt, max_tokens=16000, model=None, effort=None):
        calls.append((fmt.__name__, effort))
        if fmt is qt.WordOut:
            return fmt(translation="triển khai", detectedLang="en", lemma="deploy", ipa="/dɪˈplɔɪ/", pos="động từ",
                       meanings=["triển khai", "bố trí"], example="We deploy every day.", exampleVi="Chúng tôi triển khai mỗi ngày.")
        return fmt(translation="Bản dịch: " + content, detectedLang="en")
    monkeypatch.setattr(Translator, "__init__", fake_init)
    monkeypatch.setattr(Translator, "_parse", fake_parse)
    qt._cache.clear()
    c = TestClient(app)
    w = c.post("/api/translate", json={"text": "deploying"}).json()
    assert w["kind"] == "word" and w["lemma"] == "deploy" and w["ipa"]
    t = c.post("/api/translate", json={"text": "This paragraph explains how the agent loop works in detail."}).json()
    assert t["kind"] == "text" and t["translation"].startswith("Bản dịch")
    again = c.post("/api/translate", json={"text": "deploying"}).json()
    assert again.get("cached") and len(calls) == 2 and calls[0] == ("WordOut", "low")
    assert c.post("/api/translate", json={"text": "  "}).status_code == 400
    monkeypatch.setattr(Translator, "__init__", lambda self, *a, **k: (_ for _ in ()).throw(
        __import__("app.pipeline.translate", fromlist=["LLMUnavailable"]).LLMUnavailable("chưa có key")))
    assert c.post("/api/translate", json={"text": "new text"}).status_code == 503
