"""Xử lý tiếng Nhật: tách từ (SudachiPy), cách đọc hiragana, furigana, romaji, kanji.

Mỗi token trả về:
  {"surface","reading","lemma","lemmaReading","pos","posJa","furigana":[[base, ruby|null],...],
   "romaji","isWord"}
`furigana` chỉ đặt ruby trên phần kanji, phần okurigana giữ nguyên (vd. 忘れ → [["忘","わす"],["れ",null]]).
"""
from __future__ import annotations

import re
import threading
from functools import lru_cache

from sudachipy import Dictionary, SplitMode

_tls = threading.local()


def _tokenizer():
    # Tokenizer của Sudachi không thread-safe → mỗi thread một instance
    tok = getattr(_tls, "tok", None)
    if tok is None:
        d = Dictionary(dict="core")
        tok = d.tokenizer() if hasattr(d, "tokenizer") else d.create()
        _tls.tok = tok
    return tok


KANJI_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿々〆ヵヶ]")
KANJI_CHAR_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
KANA_RE = re.compile(r"[぀-ヿ]")

POS_MAP = {
    "名詞": "noun", "代名詞": "pronoun", "動詞": "verb", "形容詞": "i-adjective",
    "形状詞": "na-adjective", "副詞": "adverb", "助詞": "particle", "助動詞": "auxiliary",
    "感動詞": "interjection", "接続詞": "conjunction", "連体詞": "adnominal",
    "接頭辞": "prefix", "接尾辞": "suffix", "補助記号": "symbol", "記号": "symbol",
    "空白": "space",
}
CONTENT_POS = {"noun", "pronoun", "verb", "i-adjective", "na-adjective", "adverb",
               "interjection", "conjunction", "adnominal"}


def kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def has_kanji(s: str) -> bool:
    return bool(KANJI_RE.search(s))


# ---------------------------------------------------------------- romaji (Hepburn)
_ROMA = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "i", "ゑ": "e", "を": "o", "ん": "n",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o", "ゔ": "vu",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ゎ": "wa",
}
_DIGRAPH = {"ゃ": "a", "ゅ": "u", "ょ": "o"}
_SPECIAL = {"し": "sh", "ち": "ch", "じ": "j", "ぢ": "j"}
_SMALL_VOWEL = {"ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o"}


def to_romaji(kana: str) -> str:
    s = kata_to_hira(kana)
    out: list[str] = []
    i = 0
    sokuon = False
    while i < len(s):
        c = s[i]
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if c == "っ":
            sokuon = True
            i += 1
            continue
        if c == "ー":
            if out and out[-1] and out[-1][-1] in "aeiou":
                out.append(out[-1][-1])
            i += 1
            continue
        if c == "ん":
            out.append("n'" if nxt and nxt in "あいうえおやゆよ" else "n")
            i += 1
            continue
        if c in _ROMA:
            if nxt in _DIGRAPH and c not in _DIGRAPH and _ROMA[c].endswith("i") and len(_ROMA[c]) > 1:
                base = _SPECIAL.get(c, _ROMA[c][:-1] + "y")
                syl = base + _DIGRAPH[nxt]
                i += 2
            elif nxt in _SMALL_VOWEL and c in ("ふ", "て", "で", "う", "ゔ", "し", "ち", "じ"):
                head = {"ふ": "f", "て": "t", "で": "d", "う": "w", "ゔ": "v",
                        "し": "sh", "ち": "ch", "じ": "j"}[c]
                syl = head + _SMALL_VOWEL[nxt]
                i += 2
            else:
                syl = _ROMA[c]
                i += 1
            if sokuon:
                syl = ("t" if syl.startswith("ch") else syl[0]) + syl
                sokuon = False
            out.append(syl)
        else:
            if sokuon:
                sokuon = False
            out.append(c)
            i += 1
    return "".join(out)


# ---------------------------------------------------------------- furigana
def furigana_segments(surface: str, reading_hira: str) -> list[list]:
    """Căn cách đọc với mặt chữ: chỉ đặt ruby lên cụm kanji.

    Ví dụ: ("忘れ", "わすれ") → [["忘","わす"],["れ",None]]
           ("宿題", "しゅくだい") → [["宿題","しゅくだい"]]
    """
    if not has_kanji(surface) or not reading_hira:
        return [[surface, None]]
    # tách surface thành các cụm kanji / không-kanji
    runs: list[tuple[bool, str]] = []
    for ch in surface:
        k = bool(KANJI_RE.match(ch))
        if runs and runs[-1][0] == k:
            runs[-1] = (k, runs[-1][1] + ch)
        else:
            runs.append((k, ch))
    pattern = "^" + "".join(
        "(.+?)" if k else "(" + re.escape(kata_to_hira(t)) + ")" for k, t in runs
    ) + "$"
    m = re.match(pattern, reading_hira)
    if not m:
        return [[surface, reading_hira]]
    segs = []
    for (k, t), g in zip(runs, m.groups()):
        segs.append([t, g if k else None])
    return segs


# ---------------------------------------------------------------- tokenize
SPEAKER_TAG_RE = re.compile(r"[（(]([^（）()]{1,12})[）)]")


@lru_cache(maxsize=20000)
def _reading_of(text: str) -> str:
    return "".join(kata_to_hira(m.reading_form()) for m in _tokenizer().tokenize(text, SplitMode.C))


def tokenize(text: str) -> list[dict]:
    """Tách từ một câu. Nhãn người nói （チエ） được giữ thành token loại 'speaker'."""
    tokens: list[dict] = []
    pos = 0
    for m in SPEAKER_TAG_RE.finditer(text):
        if m.start() > pos:
            tokens.extend(_tokenize_plain(text[pos:m.start()]))
        tokens.append({"surface": m.group(0), "reading": "", "lemma": m.group(1),
                       "lemmaReading": "", "pos": "speaker", "posJa": "話者",
                       "furigana": [[m.group(0), None]], "romaji": "", "isWord": False})
        pos = m.end()
    if pos < len(text):
        tokens.extend(_tokenize_plain(text[pos:]))
    return tokens


def _tokenize_plain(text: str) -> list[dict]:
    out = []
    for m in _tokenizer().tokenize(text, SplitMode.C):
        surface = m.surface()
        pos_ja = m.part_of_speech()
        pos = POS_MAP.get(pos_ja[0], "other")
        if pos in ("symbol", "space") or not surface.strip():
            out.append({"surface": surface, "reading": "", "lemma": surface, "lemmaReading": "",
                        "pos": pos, "posJa": pos_ja[0], "furigana": [[surface, None]],
                        "romaji": surface if pos == "symbol" else " ", "isWord": False})
            continue
        reading = kata_to_hira(m.reading_form())
        if not KANA_RE.search(reading) and not has_kanji(surface):
            reading = kata_to_hira(surface)  # chữ Latin / số: giữ nguyên
        lemma = m.dictionary_form()
        is_proper = len(pos_ja) > 1 and pos_ja[1] == "固有名詞"
        out.append({
            "surface": surface,
            "reading": reading,
            "lemma": lemma,
            "lemmaReading": _reading_of(lemma) if lemma != surface else reading,
            "pos": pos,
            "posJa": "-".join(p for p in pos_ja[:2] if p != "*"),
            "furigana": furigana_segments(surface, reading),
            "romaji": to_romaji(reading) if KANA_RE.search(reading) else surface,
            "isWord": pos in CONTENT_POS and not is_proper and pos != "pronoun",
        })
    return out


_PUNCT_ROMA = {"。": ".", "、": ",", "！": "!", "？": "?", "…": "...", "「": '"', "」": '"', "～": "~", "〜": "~"}
_PARTICLE_ROMA = {"は": "wa", "へ": "e", "を": "o"}


def romaji_line(tokens: list[dict]) -> str:
    """Romaji cả câu: dính trợ động từ vào từ trước (ikimashita), xử lý っ cuối token."""
    groups: list[list[str]] = []   # mỗi nhóm: danh sách reading
    prev_pos = ""
    for t in tokens:
        if t["pos"] in ("speaker", "space"):
            continue
        if t["pos"] == "symbol":
            groups.append(["#" + _PUNCT_ROMA.get(t["surface"], t["surface"])])
            continue
        r = t["reading"] or t["surface"]
        if t["pos"] == "particle" and t["surface"] in _PARTICLE_ROMA:
            groups.append(["#" + _PARTICLE_ROMA[t["surface"]]])
            continue
        glue = groups and not groups[-1][0].startswith("#") and (
            t["pos"] == "auxiliary" or groups[-1][-1].endswith("っ")
            or (t["pos"] == "particle" and t["surface"] in ("て", "で")
                and prev_pos in ("verb", "auxiliary", "i-adjective")))
        if glue:
            groups[-1].append(r)
        else:
            groups.append([r])
        prev_pos = t["pos"]
    words = [g[0][1:] if g[0].startswith("#") else to_romaji("".join(g)) for g in groups]
    s = " ".join(w for w in words if w)
    return re.sub(r"\s+([.,!?~\"]+)(?=\s|$)", r"\1", s).strip()


def extract_kanji(text: str) -> list[str]:
    seen: list[str] = []
    for ch in text:
        if KANJI_CHAR_RE.match(ch) and ch not in seen:
            seen.append(ch)
    return seen


def vocab_candidates(tokens: list[dict]) -> list[dict]:
    """Danh sách từ vựng (dạng từ điển, không trùng) để LLM điền nghĩa."""
    seen = set()
    out = []
    for t in tokens:
        if not t["isWord"]:
            continue
        if len(t["lemma"]) == 1 and KANA_RE.match(t["lemma"]):
            continue   # mảnh tách sai (thường gặp với phương ngữ)
        key = t["lemma"]
        if key in seen:
            continue
        seen.add(key)
        out.append({"lemma": t["lemma"], "reading": t["lemmaReading"] or t["reading"], "pos": t["pos"]})
    return out
