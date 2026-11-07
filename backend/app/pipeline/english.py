"""Xử lý tiếng Anh cho người Việt học: tách từ, dạng gốc (lemma), chọn từ vựng đáng học.

Token có cùng cấu trúc với tiếng Nhật (japanese.py) để frontend/extension dùng chung:
  {"surface","reading":"","lemma","lemmaReading":"","pos","posJa":"","furigana":[[surface,None]],"romaji":"","isWord"}
"""
from __future__ import annotations

import re
from functools import lru_cache

TOKEN_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*|\d+(?:[.,]\d+)*|\s+|[^\sA-Za-z\d]")

# từ chức năng / rất thông dụng: vẫn tra được khi rê chuột nhưng không đưa vào danh sách từ vựng
STOPWORDS = set("""
a an the and or but if so as of at by for from in into on onto to with without about over under up down out off
than then too very just only also not no nor yes is am are was were be been being do does did done doing have has had
having i me my mine myself you your yours yourself he him his himself she her hers herself it its itself we us our ours
ourselves they them their theirs themselves this that these those there here what which who whom whose when where why how
all any both each few more most other some such own same can could will would shall should may might must let get got
gonna wanna gotta oh uh um ah okay ok yeah hey hi well like really thing things way lot lots s t d ll m re ve
one two three four five six seven eight nine ten first second
""".split())

PRONOUNS = {"i", "me", "you", "he", "him", "she", "her", "it", "we", "us", "they", "them"}


@lru_cache(maxsize=50000)
def lemma(word: str) -> str:
    w = word.lower().replace("’", "'")
    if "'" in w:                      # don't, it's, we'll → giữ nguyên dạng viết thường
        return w
    try:
        import simplemma
        return simplemma.lemmatize(w, lang="en")
    except ImportError:               # dự phòng: bỏ đuôi số nhiều đơn giản
        return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def tokenize(text: str) -> list[dict]:
    out = []
    for m in TOKEN_RE.finditer(text):
        s = m.group(0)
        if s.isspace():
            out.append(_tok(s, s, "space", False))
        elif s[0].isalpha():
            lm = lemma(s)
            # dạng rút gọn (that's, don't) và từ chức năng không đưa vào danh sách từ vựng
            word = (len(s) > 1 and not re.search(r"['’]", s)
                    and lm.lower() not in STOPWORDS and s.lower() not in STOPWORDS)
            out.append(_tok(s, lm, "pronoun" if s.lower() in PRONOUNS else "word", word))
        elif s[0].isdigit():
            out.append(_tok(s, s, "number", False))
        else:
            out.append(_tok(s, s, "symbol", False))
    return out


def _tok(surface: str, lem: str, pos: str, is_word: bool) -> dict:
    return {"surface": surface, "reading": "", "lemma": lem, "lemmaReading": "", "pos": pos, "posJa": "",
            "furigana": [[surface, None]], "romaji": "", "isWord": is_word}


def vocab_candidates(tokens: list[dict]) -> list[dict]:
    seen, out = set(), []
    for t in tokens:
        if not t["isWord"]:
            continue
        k = t["lemma"].lower()
        if k in seen:
            continue
        seen.add(k)
        out.append({"lemma": t["lemma"], "reading": "", "pos": t["pos"]})
    return out
