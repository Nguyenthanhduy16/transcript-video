"""Tạo video demo + phụ đề tiếng Nhật mẫu (hội thoại tự viết) để chạy thử pipeline không cần YouTube.

    python scripts/make_demo.py            → data/demo/demo.mp4, data/demo/demo_ja.srt
Video hiển thị đồng hồ + số cue đang nói để kiểm tra đồng bộ bằng mắt.
"""
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "demo"
OUT.mkdir(parents=True, exist_ok=True)

# (start, end, text) – hội thoại gốc, có nhạc, tiếng động, nhãn người nói, giọng Kansai
LINES = [
    (0.5, 3.0, "♪～"),
    (3.5, 5.0, "（チャイム）"),
    (5.5, 8.0, "（生徒たち）わ～い！"),
    (8.5, 11.5, "（ハル）さいなら（ソウタ）さいなら"),
    (12.0, 16.5, "（マサキ）おい ハル 宿題 忘れたらあかんで"),
    (17.0, 19.5, "（ハル）分かってるわ うるさいなあ"),
    (20.0, 24.0, "（先生）明日は漢字のテストがありますから、ちゃんと勉強してくださいね。"),
    (24.5, 26.0, "（笑い声）"),
    (26.5, 30.5, "（ソウタ）なあ ハル 帰りに駄菓子屋 寄っていかへん？"),
    (31.0, 34.0, "（ハル）ええよ でも お金 あんまり持ってへんねん"),
    (34.5, 38.0, "（ソウタ）ほな 僕が おごったるわ"),
    (38.5, 40.0, "（ハル）ほんまに？"),
    (40.5, 44.0, "～♪"),
]


def ts(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


srt = "\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n" for i, (a, b, t) in enumerate(LINES, 1))
(OUT / "demo_ja.srt").write_text(srt, encoding="utf-8")

dur = 45
# vẽ "CUE n" trong khoảng thời gian của từng câu để kiểm tra highlight
draws = [
    "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:fontsize=56:fontcolor=white:"
    "x=(w-tw)/2:y=h*0.30:text='%{pts\\:hms}'"
]
for i, (a, b, _) in enumerate(LINES, 1):
    draws.append(
        f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:fontsize=40:fontcolor=yellow:"
        f"x=(w-tw)/2:y=h*0.55:text='CUE {i}':enable='between(t,{a},{b})'")
vf = ",".join(draws)
cmd = ["ffmpeg", "-y", "-loglevel", "error",
       "-f", "lavfi", "-i", f"color=c=0x1d3557:s=1280x720:d={dur}:r=25",
       "-f", "lavfi", "-i", f"sine=frequency=330:sample_rate=16000:duration={dur}",
       "-vf", vf, "-af", "volume=0.05", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
       str(OUT / "demo.mp4")]
subprocess.run(cmd, check=True)
print("OK:", OUT / "demo.mp4", OUT / "demo_ja.srt")
