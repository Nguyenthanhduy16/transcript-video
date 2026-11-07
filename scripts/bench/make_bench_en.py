"""Audio benchmark tiếng Anh (giọng espeak-ng, 2 người nói) → data/bench/en_talk.wav + .gt.json

    python scripts/bench/make_bench_en.py     (cần espeak-ng: apt install espeak-ng)
"""
import json
import random
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "bench"
LINES = [
    ("ryan", "Welcome back to the show. Today we are talking about learning languages with videos."),
    ("amy", "Thanks for having me. I started learning Japanese three years ago."),
    ("ryan", "That's impressive. How did you find the time to study every day?"),
    ("amy", "Honestly, I watched short clips on my way to work and wrote down new words."),
    ("ryan", "Did you use subtitles in both languages?"),
    ("amy", "At first I did, but later I switched them off to train my listening."),
    ("ryan", "A lot of our listeners struggle with fast conversations."),
    ("amy", "Slowing the video down and repeating each sentence really helps."),
    ("ryan", "So shadowing is your favorite technique?"),
    ("amy", "Definitely. You copy the rhythm, and suddenly the words stick."),
    ("ryan", "What about grammar? Do you study it separately?"),
    ("amy", "I look up a pattern only when it keeps appearing in the shows I like."),
    ("ryan", "That sounds much more enjoyable than reading a textbook."),
    ("amy", "It is. The key is to stay curious and keep going, even on busy days."),
    ("ryan", "Great advice. Let's take a short break and come back with your questions."),
]


VOICES = {"amy": ["-v", "en-us+f3", "-s", "165", "-p", "60"], "ryan": ["-v", "en-us+m3", "-s", "160", "-p", "35"]}


def synth(text, spk, tmp):
    """espeak-ng (đủ để thử ASR/người nói; giọng máy, kém tự nhiên hơn giọng thật)."""
    import subprocess
    subprocess.run(["espeak-ng", *VOICES[spk], "-w", str(tmp), text], check=True)
    y, sr = sf.read(tmp, dtype="float32")
    if sr != 16000:
        from fractions import Fraction
        f = Fraction(16000, sr).limit_denominator(1000)
        y = resample_poly(y, f.numerator, f.denominator).astype(np.float32)
    nz = np.nonzero(np.abs(y) > 0.01)[0]
    return y[nz[0]:nz[-1] + 1]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_tmp_en.wav"
    rng = random.Random(3)
    parts, gt, t = [np.zeros(12000, np.float32)], [], 0.75
    for i, (spk, text) in enumerate(LINES):
        y = synth(text, spk, tmp)
        gt.append({"id": i + 1, "start": round(t, 3), "end": round(t + len(y) / 16000, 3), "speaker": spk, "text": text})
        gap = rng.uniform(0.5, 1.0)
        parts += [y, np.zeros(int(gap * 16000), np.float32)]
        t += len(y) / 16000 + int(gap * 16000) / 16000
    tmp.unlink(missing_ok=True)
    audio = np.concatenate(parts)
    sf.write(OUT / "en_talk.wav", audio, 16000)
    (OUT / "en_talk.gt.json").write_text(json.dumps({"genre": "en_talk", "condition": "sạch, TTS espeak-ng", "lang": "en",
        "durationSec": round(len(audio) / 16000, 2), "speakers": ["amy", "ryan"], "lines": gt}, ensure_ascii=False, indent=1))
    print(len(gt), "câu,", round(len(audio) / 16000, 1), "s")


if __name__ == "__main__":
    main()
