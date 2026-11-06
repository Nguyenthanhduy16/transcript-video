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


# ---------------------------------------------------------------- sửa cách đọc (số đếm, từ đặc biệt)
_DIG = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_NUM_RE = re.compile(
    r"([一二三四五六七八九十百千〇]+)(日間|週間|か月|ヶ月|カ月|か国|ページ|つ|人|本|分|回|時|歳|才|冊|枚|円|年|個|杯|匹|階|月|日|度|点|台)")
_SPECIAL_WORDS = {
    "富士山": "ふじさん", "一昨日": "おととい", "一昨年": "おととし", "明後日": "あさって",
    "大人": "おとな", "今朝": "けさ", "今年": "ことし", "眼鏡": "めがね", "八百屋": "やおや",
    "一年中": "いちねんじゅう", "一日中": "いちにちじゅう", "世界中": "せかいじゅう", "日本中": "にほんじゅう",
}
_TSU = {1: "ひとつ", 2: "ふたつ", 3: "みっつ", 4: "よっつ", 5: "いつつ", 6: "むっつ", 7: "ななつ", 8: "やっつ", 9: "ここのつ", 10: "とお"}
_DAYS = {1: "ついたち", 2: "ふつか", 3: "みっか", 4: "よっか", 5: "いつか", 6: "むいか", 7: "なのか", 8: "ようか",
         9: "ここのか", 10: "とおか", 14: "じゅうよっか", 20: "はつか", 24: "にじゅうよっか"}
_DAYS_DUR = {1: "いちにち"}
_MONTH = {4: "しがつ", 7: "しちがつ", 9: "くがつ"}
_HOUR = {4: "よじ", 7: "しちじ", 9: "くじ"}
_PERSON = {1: "ひとり", 2: "ふたり"}


def _kanji_number(s: str) -> int | None:
    total, cur = 0, 0
    for ch in s:
        if ch in _DIG:
            cur = cur * 10 + _DIG[ch] if cur and s.find("十") < 0 and s.find("百") < 0 else _DIG[ch]
        elif ch in "十百千":
            mul = {"十": 10, "百": 100, "千": 1000}[ch]
            total += (cur or 1) * mul
            cur = 0
        else:
            return None
    return total + cur


def _num_reading(n: int) -> str:
    """Đọc số 0–9999 (âm Hán), có biến âm 三百/六百/八百/三千/八千."""
    if n == 0:
        return "ぜろ"
    ones = ["", "いち", "に", "さん", "よん", "ご", "ろく", "なな", "はち", "きゅう"]
    out = ""
    th, n = divmod(n, 1000)
    if th:
        out += {1: "せん", 3: "さんぜん", 8: "はっせん"}.get(th, ones[th] + "せん")
    h, n = divmod(n, 100)
    if h:
        out += {1: "ひゃく", 3: "さんびゃく", 6: "ろっぴゃく", 8: "はっぴゃく"}.get(h, ones[h] + "ひゃく")
    t, n = divmod(n, 10)
    if t:
        out += ("" if t == 1 else ones[t]) + "じゅう"
    return out + ones[n]


def _with_counter(n: int, counter: str, prev: str, nxt: str) -> str | None:
    base = _num_reading(n)
    last = n % 10
    tens_only = n % 10 == 0 and n >= 10
    def sokuon(stem_map, default_suffix, sk_suffix, h_suffix=None):
        # 1,6,8,10 → っ + âm p/k ; 3 (và 'nan') → b/p
        r = base
        if tens_only:
            return r[:-3] + "じゅっ" + sk_suffix if r.endswith("じゅう") else r + default_suffix
        if last in (1, 6, 8):
            r = r[:-1] + "っ" if last in (1, 6) else r[:-1] + "っ"
            return r + sk_suffix
        if last == 3 and h_suffix:
            return r + h_suffix
        return r + default_suffix
    if counter == "つ" and n in _TSU:
        return _TSU[n]
    if counter == "日間":
        return (_DAYS.get(n) if n != 1 else "いちにち") + "かん" if (n in _DAYS or n == 1) else base + "にちかん"
    if counter == "日":
        if n in _DAYS and (n != 1 or prev.endswith("月")):
            return _DAYS[n]
        if n == 1:
            return "いちにち"
        return base + "にち"
    if counter == "月":
        return _MONTH.get(n, base + "がつ")
    if counter == "時":
        return _HOUR.get(n, base + "じ")
    if counter == "人":
        return _PERSON.get(n, (base[:-2] + "よ" if base.endswith("よん") else base) + "にん")
    if counter == "分":
        if n == 10 and prev == "十" and not re.match(r"(ぐらい|くらい|ほど|後|前|間|で(?!す)|かかり|かかる|おき|待|も|しか)", nxt):
            return "じゅうぶん"                   # 十分 = "đủ"
        if last in (1, 6, 8) or tens_only:
            return sokuon(None, "ふん", "ぷん")
        if last in (3, 4) or base.endswith("さん") or base.endswith("よん"):
            return base + "ぷん"
        return base + "ふん"
    if counter in ("本", "杯", "匹"):
        h, b, p = {"本": ("ほん", "ぼん", "ぽん"), "杯": ("はい", "ばい", "ぱい"), "匹": ("ひき", "びき", "ぴき")}[counter]
        if last in (1, 6, 8) or tens_only:
            return sokuon(None, h, p)
        if last == 3:
            return base + b
        return base + h
    if counter in ("回", "個", "階", "か月", "ヶ月", "カ月", "か国"):
        k = {"回": "かい", "個": "こ", "階": "かい", "か月": "かげつ", "ヶ月": "かげつ", "カ月": "かげつ", "か国": "かこく"}[counter]
        if last in (1, 6, 8) or tens_only:
            return sokuon(None, k, k)
        if counter == "階" and last == 3:
            return base + "がい"
        return base + k
    if counter in ("冊", "歳", "才", "週間", "点"):
        k = {"冊": "さつ", "歳": "さい", "才": "さい", "週間": "しゅうかん", "点": "てん"}[counter]
        if n == 20 and counter in ("歳", "才"):
            return "はたち"
        if last in (1, 8) or tens_only:
            return sokuon(None, k, k)
        return base + k
    if counter == "円" and last == 4:
        return base[:-2] + "よえん"
    simple = {"枚": "まい", "円": "えん", "年": "ねん", "度": "ど", "台": "だい", "ページ": "ぺーじ"}
    if counter in simple:
        if counter == "年" and last == 4:
            return base[:-2] + "よねん"
        return base + simple[counter]
    return None


def _fix_readings(text: str, toks: list[dict]) -> list[dict]:
    """Gộp token theo các mẫu số + đơn vị đếm / từ đặc biệt và đặt lại cách đọc."""
    spans: list[tuple[int, int, str]] = []
    for w, r in _SPECIAL_WORDS.items():
        for m in re.finditer(re.escape(w), text):
            spans.append((m.start(), m.end(), r))
    for m in _NUM_RE.finditer(text):
        if any(a < m.end() and m.start() < b for a, b, _ in spans):
            continue
        n = _kanji_number(m.group(1))
        if n is None:
            continue
        prev = m.group(1) if m.group(1) == "十" else text[:m.start()]
        r = _with_counter(n, m.group(2), prev, text[m.end():])
        if r:
            spans.append((m.start(), m.end(), r))
    # vị trí ký tự của token
    pos, offs = 0, []
    for t in toks:
        offs.append((pos, pos + len(t["surface"])))
        pos += len(t["surface"])
    out, i = [], 0
    for a, b, r in sorted(spans):
        # chỉ thay khi ranh giới mẫu trùng ranh giới token
        idx = [k for k, (x, y) in enumerate(offs) if x >= a and y <= b]
        if not idx or offs[idx[0]][0] != a or offs[idx[-1]][1] != b or idx[0] < i:
            continue
        out.extend(toks[i:idx[0]])
        surf = text[a:b]
        first = toks[idx[0]]
        out.append({**first, "surface": surf, "reading": r, "lemma": surf, "lemmaReading": r,
                    "furigana": furigana_segments(surf, r), "romaji": to_romaji(r),
                    "isWord": surf in _SPECIAL_WORDS and first["pos"] == "noun"})
        i = idx[-1] + 1
    out.extend(toks[i:])
    # quy tắc theo ngữ cảnh
    for k, t in enumerate(out):
        nxt = out[k + 1]["surface"] if k + 1 < len(out) else ""
        prev = out[k - 1] if k > 0 else None
        if t["surface"] == "何" and nxt[:1] in ("も", "を", "が", "に") and t["reading"] != "なに":
            t.update(reading="なに", lemmaReading="なに", furigana=[["何", "なに"]], romaji="nani")
        if t["lemma"] == "言う" and t["reading"].startswith("ゆ"):
            r = "い" + t["reading"][1:]
            t.update(reading=r, lemmaReading="いう", furigana=furigana_segments(t["surface"], r), romaji=to_romaji(r))
        if prev and prev["pos"] == "noun" and t["surface"] in ("作り", "造り", "勝ち"):
            r = {"作り": "づくり", "造り": "づくり", "勝ち": "がち"}[t["surface"]]
            t.update(reading=r, furigana=furigana_segments(t["surface"], r), romaji=to_romaji(r))
    return out


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
    return _fix_readings(text, _tokenize_raw(text))


def _tokenize_raw(text: str) -> list[dict]:
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
