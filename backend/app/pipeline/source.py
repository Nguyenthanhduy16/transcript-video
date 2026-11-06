"""Lấy nguồn: YouTube / link trang video / link file media / file upload.

Lưu ý bản quyền: tải audio từ YouTube có thể vi phạm Điều khoản dịch vụ của YouTube.
Chỉ dùng với nội dung được phép; trình phát luôn là YouTube IFrame (không phát lại file tải về).
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..config import MEDIA_DIR

YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"}
MEDIA_EXT = (".mp4", ".m4v", ".webm", ".mkv", ".mov", ".mp3", ".m4a", ".wav", ".m3u8", ".ogg", ".flac")
SUB_LANG_PREF = {"ja": ["ja", "ja-JP", "ja-orig"], "ko": ["ko"], "zh": ["zh-Hans", "zh", "zh-CN", "zh-TW"], "en": ["en", "en-US"]}


class SourceError(RuntimeError):
    pass


def youtube_id(url: str) -> str | None:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if host not in YT_HOSTS:
        return None
    if host == "youtu.be":
        return u.path.lstrip("/").split("/")[0] or None
    if u.path == "/watch":
        return parse_qs(u.query).get("v", [None])[0]
    m = re.match(r"^/(shorts|embed|live)/([\w-]{6,})", u.path)
    return m.group(2) if m else None


def make_video_id(seed: str) -> str:
    return "v" + hashlib.sha1(seed.encode()).hexdigest()[:10]


def kind_of(url: str) -> str:
    if youtube_id(url):
        return "youtube"
    path = urlparse(url).path.lower()
    if path.endswith(MEDIA_EXT):
        return "media"
    return "page"   # trang video khác → để yt-dlp xử lý


def extract_audio(src: str | Path, out_wav: Path) -> Path:
    """ffmpeg → WAV 16 kHz mono (đầu vào chuẩn cho Whisper)."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
           "-c:a", "pcm_s16le", str(out_wav)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SourceError(f"ffmpeg lỗi: {r.stderr.strip()[-400:]}")
    return out_wav


def probe_duration(src: str | Path) -> float | None:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                        "default=nw=1:nk=1", str(src)], capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 3)
    except ValueError:
        return None


def _ydl(opts: dict):
    try:
        import yt_dlp
    except ImportError as e:   # pragma: no cover
        raise SourceError("Chưa cài yt-dlp") from e
    base = {"quiet": True, "no_warnings": True, "noplaylist": True}
    base.update(opts)
    return yt_dlp.YoutubeDL(base)


def fetch_info(url: str) -> dict:
    try:
        with _ydl({"skip_download": True}) as y:
            return y.extract_info(url, download=False)
    except Exception as e:
        raise SourceError(f"Không đọc được thông tin video: {e}") from e


def pick_subtitle(info: dict, lang: str, allow_auto: bool) -> tuple[str, str] | None:
    """Trả về (mã ngôn ngữ, 'manual'|'auto') – ưu tiên phụ đề làm tay."""
    prefs = SUB_LANG_PREF.get(lang, [lang])
    for key, kind in (("subtitles", "manual"), ("automatic_captions", "auto")):
        if kind == "auto" and not allow_auto:
            continue
        tracks = info.get(key) or {}
        for code in prefs:
            if code in tracks:
                return code, kind
    return None


def download_subtitle(url: str, code: str, kind: str, workdir: Path) -> Path:
    opts = {"skip_download": True, "subtitleslangs": [code], "subtitlesformat": "vtt/srt/best",
            "outtmpl": str(workdir / "sub.%(ext)s")}
    opts["writesubtitles" if kind == "manual" else "writeautomaticsub"] = True
    with _ydl(opts) as y:
        y.download([url])
    files = sorted(workdir.glob("sub.*.vtt")) + sorted(workdir.glob("sub.*.srt"))
    if not files:
        raise SourceError("Tải phụ đề thất bại")
    return files[0]


def download_audio(url: str, workdir: Path) -> Path:
    opts = {"format": "bestaudio/best", "outtmpl": str(workdir / "audio_src.%(ext)s")}
    with _ydl(opts) as y:
        y.download([url])
    files = [p for p in workdir.glob("audio_src.*") if p.suffix != ".part"]
    if not files:
        raise SourceError("Tải audio thất bại")
    return extract_audio(files[0], workdir / "audio.wav")


def download_video(url: str, workdir: Path) -> Path:
    """Dùng cho link trang video khác (không phải YouTube): tải file mp4 để phát bằng HTML5."""
    opts = {"format": "best[ext=mp4]/best", "outtmpl": str(workdir / "video.%(ext)s")}
    with _ydl(opts) as y:
        y.download([url])
    files = [p for p in workdir.glob("video.*") if p.suffix != ".part"]
    if not files:
        raise SourceError("Tải video thất bại")
    return files[0]


def media_dir(video_id: str) -> Path:
    d = MEDIA_DIR / video_id
    d.mkdir(parents=True, exist_ok=True)
    return d
