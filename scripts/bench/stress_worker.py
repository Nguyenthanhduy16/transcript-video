"""Nghiệm thu P1-4: 20 job liên tiếp qua hàng đợi BullMQ (Redis) + worker riêng, không crash.

    python scripts/bench/stress_worker.py        (cần redis-server, đã chạy make_bench.py)

Dựng: redis-server (cổng 6390), HTTP server nội bộ phục vụ file mp4 / HLS (.m3u8) / file hỏng…,
1 process worker (`python -m app.worker`). Đẩy 20 job gồm job hợp lệ và job lỗi cố ý, rồi kiểm tra:
  - mọi job kết thúc (done/error), không job nào treo;
  - job lỗi có mã + lý do rõ ràng, đúng loại lỗi mong đợi;
  - worker vẫn sống sau 20 job.
Kết quả: data/bench/results/worker_stress.json
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "data" / "bench"
WORK = BENCH / "stress"
PORT_REDIS, PORT_HTTP = 6390, 8811
os.environ.update(QUEUE_BACKEND="redis", REDIS_URL=f"redis://localhost:{PORT_REDIS}", QUEUE_NAME="transcript-stress",
                  LLM_PROVIDER="none", DATA_DIR=str(WORK / "data"))
sys.path.insert(0, str(ROOT / "backend"))


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def fixtures():
    srv = WORK / "www"
    srv.mkdir(parents=True, exist_ok=True)
    # clip 40 s từ bộ benchmark, ghép hình màu để thành video
    for g, start in (("news", 0), ("anime", 20), ("variety", 40)):
        ff("-f", "lavfi", "-i", "color=c=0x223344:s=320x180:r=10", "-ss", str(start), "-t", "40", "-i", str(BENCH / f"{g}.wav"),
           "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(srv / f"{g}.mp4"))
    # HLS
    hls = srv / "hls"
    hls.mkdir(exist_ok=True)
    ff("-i", str(srv / "news.mp4"), "-c", "copy", "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod",
       str(hls / "index.m3u8"))
    (srv / "page.html").write_text("<html><body>không phải video</body></html>")
    (srv / "corrupt.mp4").write_bytes(os.urandom(200_000))
    ff("-f", "lavfi", "-i", "color=c=red:s=160x90:d=5", "-c:v", "libx264", "-preset", "ultrafast", str(srv / "noaudio.mp4"))
    ff("-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "20", str(srv / "silence.wav"))
    (srv / "noaudio.srt").write_text("1\n00:00:00,500 --> 00:00:02,500\n（ハル）ほんまに？\n\n", encoding="utf-8")
    return srv


def serve(directory: Path):
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(directory), **k)  # noqa: E731
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", PORT_HTTP), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def upload(srv: Path, name: str, vid: str, sub: str | None = None) -> dict:
    """Giả lập API upload: chép file vào thư mục media (dùng chung giữa API và worker)."""
    d = WORK / "data" / "media" / vid
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(srv / name, d / name)
    p = {"video_id": vid, "upload_path": str(d / name), "original_name": name, "lang": "ja", "target": "vi"}
    if sub:
        shutil.copy(srv / sub, d / sub)
        p["subtitle_path"] = str(d / sub)
    return p


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    srv = fixtures()
    httpd = serve(srv)
    redis = subprocess.Popen(["redis-server", "--port", str(PORT_REDIS), "--save", "", "--appendonly", "no"],
                             stdout=subprocess.DEVNULL)
    time.sleep(1)
    log = open(WORK / "worker.log", "w")
    worker = subprocess.Popen([sys.executable, "-m", "app.worker"], cwd=ROOT / "backend", stdout=log, stderr=log, env=os.environ)
    time.sleep(3)
    from app.queue import RedisQueue
    q = RedisQueue()
    H = f"http://127.0.0.1:{PORT_HTTP}"
    cases = [  # (mô tả, params, kết quả mong đợi: "done" | mã lỗi)
        ("upload mp4 tin tức (ASR)", upload(srv, "news.mp4", "s01"), "done"),
        ("upload mp4 anime (ASR)", upload(srv, "anime.mp4", "s02"), "done"),
        ("upload mp4 show (ASR)", upload(srv, "variety.mp4", "s03"), "done"),
        ("link mp4 http", {"url": f"{H}/news.mp4", "video_id": "s04", "lang": "ja"}, "done"),
        ("link mp4 http, biết số người nói", {"url": f"{H}/anime.mp4", "video_id": "s05", "lang": "ja", "num_speakers": 4}, "done"),
        ("link HLS .m3u8", {"url": f"{H}/hls/index.m3u8", "video_id": "s06", "lang": "ja"}, "done"),
        ("link 404", {"url": f"{H}/khong-co.mp4", "video_id": "s07", "lang": "ja"}, "SOURCE_NOT_FOUND"),
        ("trang HTML không phải video", {"url": f"{H}/page.html", "video_id": "s08", "lang": "ja"}, "UNSUPPORTED_URL"),
        ("upload file hỏng", upload(srv, "corrupt.mp4", "s09"), "NOT_MEDIA"),
        ("video không có tiếng, không phụ đề", upload(srv, "noaudio.mp4", "s10"), "NO_AUDIO"),
        ("video không có tiếng + phụ đề .srt", upload(srv, "noaudio.mp4", "s11", "noaudio.srt"), "done"),
        ("audio toàn im lặng", upload(srv, "silence.wav", "s12"), "NO_SPEECH"),
        ("máy chủ không tồn tại", {"url": "http://127.0.0.1:9/x.mp4", "video_id": "s13", "lang": "ja"}, "SOURCE_UNREACHABLE"),
        ("giao thức không hỗ trợ", {"url": "ftp://example.com/a.mp4", "video_id": "s14", "lang": "ja"}, "UNSUPPORTED_URL"),
        ("link HLS lần 2", {"url": f"{H}/hls/index.m3u8", "video_id": "s15", "lang": "ja"}, "done"),
        ("upload mp4 show lần 2", upload(srv, "variety.mp4", "s16"), "done"),
        ("dịch lại video không tồn tại", {"video_id": "khong-ton-tai", "ids": None}, "NOT_FOUND"),
        ("link mp4 show", {"url": f"{H}/variety.mp4", "video_id": "s18", "lang": "ja"}, "done"),
        ("upload mp4 tin tức lần 2", upload(srv, "news.mp4", "s19"), "done"),
        ("link 404 lần 2", {"url": f"{H}/mat.m3u8", "video_id": "s20", "lang": "ja"}, "SOURCE_NOT_FOUND"),
    ]
    t0 = time.time()
    ids = []
    for i, (desc, params, _) in enumerate(cases):
        kind = "retranslate" if desc.startswith("dịch lại") else "transcript"
        ids.append(q.submit(kind, params, desc)["id"])
    results = {}
    while time.time() - t0 < 1800:
        states = {jid: q.get(jid) for jid in ids}
        if all(s and s["status"] in ("done", "error") for s in states.values()):
            results = states
            break
        if worker.poll() is not None:
            break
        time.sleep(2)
    alive = worker.poll() is None
    rows = []
    for (desc, _, expect), jid in zip(cases, ids):
        j = results.get(jid) or q.get(jid) or {}
        code = (j.get("error") or "").split(":")[0] if j.get("status") == "error" else "done"
        ok = (j.get("status") == "done") if expect == "done" else (j.get("status") == "error" and code == expect)
        rows.append({"job": desc, "status": j.get("status"), "expected": expect, "pass": ok,
                     "error": j.get("error"), "attempts": j.get("attempts"),
                     "cues": (j.get("stats") or {}).get("cueCount"), "sec": (j.get("stats") or {}).get("totalSec")})
    summary = {"jobs": len(rows), "finished": sum(r["status"] in ("done", "error") for r in rows),
               "asExpected": sum(r["pass"] for r in rows), "workerAlive": alive, "elapsedSec": round(time.time() - t0, 1),
               "rows": rows}
    out = BENCH / "results"
    out.mkdir(parents=True, exist_ok=True)
    (out / "worker_stress.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows:
        print(f"{'✓' if r['pass'] else '✗'} {r['job']:38} {r['status'] or '-':6} {(r['error'] or '')[:95]}")
    print(f"\n{summary['finished']}/{summary['jobs']} job kết thúc, {summary['asExpected']} đúng kỳ vọng, "
          f"worker còn sống: {alive}, {summary['elapsedSec']} s")
    worker.terminate()
    worker.wait(30)
    redis.terminate()
    httpd.shutdown()


if __name__ == "__main__":
    main()
