"""Tạo bộ audio benchmark có đáp án (ground truth) cho tool transcript.

    python scripts/bench/make_bench.py            → data/bench/{news,anime,variety}[_clean].wav + *.gt.json
    python scripts/bench/make_bench.py --long 50  → thêm data/bench/long50.wav (~50 phút) để đo tốc độ

Giọng: pyopenjtalk (TTS tiếng Nhật). Mỗi người nói đổi "độ dài thanh quản" bằng cách tổng hợp chậm k lần
rồi resample nhanh k lần (formant × k) + đổi cao độ → embedding người nói khác nhau thật sự.
Nhiễu: tin tức sạch; anime có nhạc nền (SNR ~15 dB); show thực tế có tiếng ồn đám đông (SNR ~18 dB).
Đáp án: mốc bắt đầu/kết thúc phần có tiếng của từng câu (đã cắt im lặng), câu gốc, người nói.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pyopenjtalk
import soundfile as sf
from scipy.signal import lfilter, resample_poly

sys.path.insert(0, str(Path(__file__).parent))
from corpus import GENRES, VOICES  # noqa: E402

SR = 16000
OUT = Path(__file__).resolve().parents[2] / "data" / "bench"


def synth(text: str, voice: str) -> np.ndarray:
    k, h = VOICES[voice]
    x, sr = pyopenjtalk.tts(text, speed=1 / k, half_tone=h)          # 48 kHz
    f = Fraction(SR, int(round(sr * k))).limit_denominator(400)
    y = resample_poly(x, f.numerator, f.denominator) / 32768.0
    nz = np.nonzero(np.abs(y) > 0.01)[0]
    y = y[max(0, nz[0] - 16):nz[-1] + 16]                              # cắt im lặng hai đầu
    return (0.6 * y / (np.abs(y).max() + 1e-9)).astype(np.float32)


def music_bed(n: int, rng: random.Random) -> np.ndarray:
    """Nhạc nền đơn giản: hợp âm thay đổi mỗi 2 giây + nhịp trống nhẹ."""
    t = np.arange(n) / SR
    out = np.zeros(n, np.float32)
    chords = [(261.6, 329.6, 392.0), (220.0, 261.6, 329.6), (174.6, 220.0, 261.6), (196.0, 246.9, 293.7)]
    for i in range(0, n, 2 * SR):
        seg = slice(i, min(n, i + 2 * SR))
        for f in chords[(i // (2 * SR)) % 4]:
            out[seg] += 0.2 * np.sin(2 * np.pi * f * t[seg]) * np.exp(-((t[seg] - t[seg][0]) % 0.5) * 3)
    kick = np.exp(-np.arange(int(0.12 * SR)) / 400) * np.sin(2 * np.pi * 60 * np.arange(int(0.12 * SR)) / SR)
    for i in range(0, n - len(kick), SR // 2):
        out[i:i + len(kick)] += 0.5 * kick
    return out


def crowd(n: int, rng: np.random.Generator) -> np.ndarray:
    """Tiếng ồn đám đông: nhiễu hồng có biên độ dao động chậm."""
    w = rng.standard_normal(n).astype(np.float32)
    pink = lfilter([0.049922035, -0.095993537, 0.050612699, -0.004408786], [1, -2.494956002, 2.017265875, -0.522189400], w)
    env = 0.6 + 0.4 * np.sin(2 * np.pi * 0.3 * np.arange(n) / SR + rng.uniform(0, 6))
    return (pink * env).astype(np.float32)


def mix(speech: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    ps = np.mean(speech[np.abs(speech) > 0.01] ** 2)
    pn = np.mean(noise ** 2) + 1e-12
    y = speech + noise * np.sqrt(ps / (pn * 10 ** (snr_db / 10)))
    return (y / max(1.0, np.abs(y).max() / 0.95)).astype(np.float32)


def build(lines, seed: int):
    rng = random.Random(seed)
    parts, gt, t = [np.zeros(int(0.8 * SR), np.float32)], [], 0.8
    for i, (spk, text) in enumerate(lines):
        y = synth(text, spk)
        gt.append({"id": i + 1, "start": round(t, 3), "end": round(t + len(y) / SR, 3), "speaker": spk, "text": text})
        gap = rng.uniform(0.4, 1.0)
        parts += [y, np.zeros(int(gap * SR), np.float32)]
        t += len(y) / SR + int(gap * SR) / SR
    return np.concatenate(parts), gt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--long", type=float, default=0, help="tạo thêm file dài N phút")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    nrng = np.random.default_rng(7)
    cache = {}
    for gi, (genre, lines) in enumerate(GENRES.items()):
        clean, gt = build(lines, seed=gi)
        cache[genre] = (clean, gt)
        sf.write(OUT / f"{genre}_clean.wav", clean, SR)
        if genre == "anime":
            noisy = mix(clean, music_bed(len(clean), random.Random(1)), 15)
            cond = "nhạc nền SNR 15 dB"
        elif genre == "variety":
            noisy = mix(clean, crowd(len(clean), nrng), 18)
            cond = "ồn đám đông SNR 18 dB"
        else:
            noisy, cond = clean, "sạch"
        sf.write(OUT / f"{genre}.wav", noisy, SR)
        meta = {"genre": genre, "condition": cond, "durationSec": round(len(clean) / SR, 2),
                "speakers": sorted({g["speaker"] for g in gt}), "lines": gt}
        (OUT / f"{genre}.gt.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{genre}: {len(gt)} câu, {meta['durationSec']} s, {len(meta['speakers'])} người nói, {cond}")
    if args.long:
        target = args.long * 60 * SR
        parts, gts, off = [], [], 0
        while off < target:
            for genre, (a, gt) in cache.items():
                parts.append(a)
                gts += [{**g, "start": round(g["start"] + off / SR, 3), "end": round(g["end"] + off / SR, 3)} for g in gt]
                off += len(a)
        a = np.concatenate(parts)
        sf.write(OUT / f"long{int(args.long)}.wav", a, SR)
        (OUT / f"long{int(args.long)}.gt.json").write_text(json.dumps(
            {"genre": "long", "condition": "sạch, ghép lặp 3 thể loại", "durationSec": round(len(a) / SR, 2),
             "speakers": sorted({g["speaker"] for g in gts}), "lines": gts}, ensure_ascii=False), encoding="utf-8")
        print(f"long: {len(a) / SR / 60:.1f} phút, {len(gts)} câu")


if __name__ == "__main__":
    main()
