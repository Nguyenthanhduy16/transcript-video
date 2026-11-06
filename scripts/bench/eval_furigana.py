"""Đo độ đúng furigana (cách đọc từ có kanji) trên ≥ 200 câu.

Phương pháp (chưa có bộ gán tay của Người 4):
1. Câu mẫu = các câu có kanji trong corpus.py + EXTRA dưới đây (số đếm, từ nhiều cách đọc, tên riêng…).
2. Cách đọc của tool (SudachiPy) được so với OpenJTalk (pyopenjtalk, từ điển NAIST-JDIC – độc lập).
   Hai cách tách từ khác nhau nên so theo "đơn vị căn chỉnh": gộp token tới khi hai bên có chung ranh giới.
3. Đơn vị có kanji mà hai bên giống nhau → coi là đúng.
   Khác nhau → tra bảng GOLD (người phân xử điền đáp án đúng) → đúng nếu tool khớp GOLD.
   Chưa có trong GOLD → in ra để phân xử, tạm tính là SAI.
4. Ngoài ra kiểm tra tính nhất quán: ghép các đoạn furigana (ruby + okurigana) phải ra đúng cách đọc.

    python scripts/bench/eval_furigana.py            → in kết quả + data/bench/results/furigana.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).parent))

import pyopenjtalk  # noqa: E402
from app.pipeline import japanese as ja  # noqa: E402
from corpus import GENRES  # noqa: E402

EXTRA = [
    "一日に三回、薬を飲んでください。", "今日は四月一日です。", "二十日に友達が来ます。",
    "りんごを五つと、みかんを八つ買いました。", "一人で行くのは怖いので、二人で行きましょう。",
    "大人になったら、医者になりたいです。", "上手に日本語を話せるようになりたい。",
    "昨日、図書館で本を三冊借りました。", "駅から歩いて十分ぐらいです。", "毎朝六時に起きます。",
    "この問題は、思ったより簡単でした。", "雨が降りそうなので、傘を持っていきます。",
    "日曜日に家族と映画を見に行きました。", "生まれた町は、海の近くにあります。",
    "先生に宿題を出すのを忘れました。", "風邪をひいて、学校を休みました。",
    "会議は午前十時から始まります。", "冷蔵庫に牛乳が入っています。",
    "この漢字の読み方を教えてください。", "電話番号を間違えてしまいました。",
    "春になると、桜がきれいに咲きます。", "今年の夏は、去年より暑いです。",
    "彼は毎日、自転車で会社に通っています。", "部屋の掃除を手伝ってくれませんか。",
    "新しい仕事にはもう慣れましたか。", "時間がないので、急いでください。",
    "子供たちが公園で元気に遊んでいます。", "台所で母が晩ご飯を作っています。",
    "次の駅で電車を乗り換えます。", "財布を落としたので、交番に行きました。",
    "東京から大阪まで、新幹線で二時間半かかります。", "百円玉を三枚ください。",
    "七日の金曜日は都合が悪いです。", "八百屋で野菜を買いました。", "九月九日は重陽の節句です。",
    "兄は大学で経済を勉強しています。", "妹はピアノが上手です。", "祖父は八十歳になりました。",
    "日本の人口は約一億二千万人です。", "この川は、町の真ん中を流れています。",
    "体に気をつけて、頑張ってください。", "明後日までに返事をください。",
    "一昨日、久しぶりに雪が降りました。", "店の前に長い列ができています。",
    "この料理は、どうやって作るんですか。", "外国人の観光客が増えています。",
    "試験に合格して、とても嬉しかったです。", "銀行でお金を下ろしてきます。",
    "眼鏡をかけると、よく見えます。", "海外旅行の準備で忙しいです。",
    "この辺りは、夜になると静かです。", "交通事故に気をつけましょう。",
    "最近、運動不足で太りました。", "手紙を書いて、郵便局で出しました。",
    "地下鉄の入口はどこですか。", "今朝は、何も食べていません。",
    "部長は今、外出中です。", "工場で働く人が足りません。",
    "博物館は月曜日が休みです。", "今度の土曜日、一緒に買い物に行きませんか。",
]

# Tập giữ lại (held-out): viết SAU khi đã sửa quy tắc đọc, không dùng để chỉnh tool.
HELDOUT = [
    "三日前から熱が下がりません。", "五月五日はこどもの日です。", "六時半に駅の改札で会いましょう。",
    "鉛筆を十本と消しゴムを一個ください。", "この建物は三階建てです。", "三人の兄弟がいます。",
    "二週間後に引っ越します。", "毎月二十五日に給料が出ます。", "四人分のケーキを予約しました。",
    "八時十五分の電車に乗ります。", "犬を二匹飼っています。", "去年、三か国を旅行しました。",
    "牛乳を一杯飲みました。", "四年ぶりに国へ帰ります。", "九時から五時まで働いています。",
    "彼女は二十歳になったばかりです。", "部屋に机が二台あります。", "本を一冊読み終えました。",
    "お皿を六枚並べてください。", "試合は一対一の引き分けでした。", "上手な料理人になりたい。",
    "姉は銀行に勤めています。", "週末は天気が崩れるでしょう。", "空港までタクシーで行きました。",
    "地図を見ながら道を探しました。", "長い間、連絡しなくてごめんなさい。", "夕方から雨が強くなるそうです。",
    "店員さんに道を聞きました。", "野菜は体にいいです。", "日本酒を少しだけ飲みました。",
    "あの人は有名な歌手です。", "大切な書類をなくしてしまいました。", "朝ご飯は毎日食べます。",
    "子供の頃、よく川で泳ぎました。", "暗い所で本を読むと目が悪くなります。", "次の角を右に曲がってください。",
    "今週の土曜日は仕事が休みです。", "風が強くて、窓が揺れています。", "この町には古いお寺がたくさんあります。",
    "宿題は自分でやりなさい。",
]

# Phân xử các trường hợp hai bộ phân tích đọc khác nhau: (mặt chữ đơn vị) → cách đọc đúng trong câu.
# Điền sau khi chạy lần đầu (mục "disagreements" trong kết quả).
GOLD_PATH = Path(__file__).parent / "furigana_gold.json"


def kata2hira(s: str) -> str:
    return ja.kata_to_hira(s)


def ojt_tokens(text: str):
    out = []
    for w in pyopenjtalk.run_frontend(text):
        s = w["string"]
        r = w["read"] if w["read"] and w["read"] != "、" else s
        out.append((s, kata2hira(r)))
    return out


def units(text: str):
    ours = [(t["surface"], t["reading"] or t["surface"], t) for t in ja.tokenize(text) if t["pos"] != "space"]
    theirs = ojt_tokens(text)
    i = j = 0
    pi = pj = 0
    cur_o, cur_t = [], []
    res = []
    while i < len(ours) or j < len(theirs):
        if pi <= pj and i < len(ours):
            cur_o.append(ours[i]); pi += len(ours[i][0]); i += 1
        elif j < len(theirs):
            cur_t.append(theirs[j]); pj += len(theirs[j][0]); j += 1
        else:
            cur_o.append(ours[i]); pi += len(ours[i][0]); i += 1
        if pi == pj and cur_o and cur_t:
            res.append((cur_o, cur_t))
            cur_o, cur_t = [], []
    if cur_o or cur_t:
        res.append((cur_o, cur_t))
    return res


def main():
    held = "--heldout" in sys.argv
    sents = HELDOUT if held else [t for lines in GENRES.values() for _, t in lines] + EXTRA
    sents = [re.sub(r"[　 ]", "", s) for s in sents if ja.has_kanji(s)]
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8")) if GOLD_PATH.exists() else {}
    total_units = ok_units = kanji_words = ok_words = 0
    disagreements, wrong, inconsistent = [], [], []
    for s in sents:
        for o, t in units(s):
            surf = "".join(x[0] for x in o)
            if not ja.has_kanji(surf):
                continue
            n_words = sum(1 for x in o if ja.has_kanji(x[0]))
            our_r = "".join(x[1] for x in o)
            ojt_r = "".join(x[1] for x in t)
            total_units += 1
            kanji_words += n_words
            key = f"{s}|{surf}"
            if key in gold:              # đã phân xử thì luôn theo GOLD (kể cả khi hai bộ đồng ý)
                ok = our_r in gold[key].split("/")
                if our_r != ojt_r or not ok:
                    disagreements.append({"sentence": s, "surface": surf, "tool": our_r, "openjtalk": ojt_r, "gold": gold[key]})
                    if not ok:
                        wrong.append(disagreements[-1])
            elif our_r == ojt_r:
                ok = True
            else:
                g = gold.get(key)
                ok = g is not None and our_r in g.split("/")
                disagreements.append({"sentence": s, "surface": surf, "tool": our_r, "openjtalk": ojt_r, "gold": g})
                if not ok:
                    wrong.append(disagreements[-1])
            ok_units += ok
            ok_words += n_words if ok else 0
            for x in o:   # nhất quán furigana ↔ cách đọc
                tok = x[2]
                if ja.has_kanji(tok["surface"]):
                    rebuilt = "".join(r if r else kata2hira(b) for b, r in tok["furigana"])
                    if rebuilt != tok["reading"]:
                        inconsistent.append({"surface": tok["surface"], "reading": tok["reading"], "furigana": tok["furigana"]})
    res = {"sentences": len(sents), "kanjiUnits": total_units, "kanjiWords": kanji_words,
           "accuracyPct": round(100 * ok_words / kanji_words, 2),
           "agreeWithoutGoldPct": round(100 * (total_units - len(disagreements)) / total_units, 2),
           "disagreements": disagreements, "wrong": wrong, "inconsistentFurigana": inconsistent}
    out = ROOT / "data" / "bench" / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / ("furigana_heldout.json" if held else "furigana.json")).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(sents)} câu, {kanji_words} từ có kanji ({total_units} đơn vị) | đúng {res['accuracyPct']}% "
          f"| hai bộ phân tích đồng ý {res['agreeWithoutGoldPct']}% | lệch {len(disagreements)}, sai {len(wrong)}, "
          f"furigana không nhất quán {len(inconsistent)}")
    for w in wrong:
        print(f"  {w['surface']}: tool={w['tool']} ojt={w['openjtalk']} gold={w['gold']} | {w['sentence']}")


if __name__ == "__main__":
    main()
