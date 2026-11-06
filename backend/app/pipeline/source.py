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
    """Lỗi nguồn video, có mã để CMS/backend hiển thị và quyết định thử lại."""

    def __init__(self, message: str, code: str = "SOURCE_ERROR", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


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
    if not url.startswith(("http://", "https://")):
        raise SourceError("Link phải bắt đầu bằng http:// hoặc https:// (giao thức khác chưa hỗ trợ)", "UNSUPPORTED_URL")
    if youtube_id(url):
        return "youtube"
    path = urlparse(url).path.lower()
    if path.endswith(MEDIA_EXT):
        return "media"
    return "page"   # trang video khác → để yt-dlp xử lý


MAX_DURATION_MIN = float(__import__("os").getenv("MAX_DURATION_MIN", "180"))
NET_TIMEOUT_SEC = 30


def _is_url(src) -> bool:
    return str(src).startswith(("http://", "https://"))


def _net_opts(src) -> list[str]:
    # timeout mạng (µs) + tự nối lại khi tải link http/m3u8
    return ["-rw_timeout", str(NET_TIMEOUT_SEC * 1_000_000), "-reconnect", "1", "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5"] if _is_url(src) else []


def _ffmpeg_error(stderr: str, src) -> SourceError:
    e = stderr.lower()
    if "404" in e or ("not found" in e and _is_url(src)):
        return SourceError("Không tải được link (HTTP 404 – không tìm thấy). Kiểm tra lại đường dẫn.", "SOURCE_NOT_FOUND")
    if "403" in e or "401" in e:
        return SourceError("Máy chủ từ chối truy cập link (HTTP 401/403).", "SOURCE_FORBIDDEN")
    if "timed out" in e or "timeout" in e:
        return SourceError("Hết thời gian chờ khi tải link (mạng chậm hoặc máy chủ không phản hồi).", "SOURCE_TIMEOUT", True)
    if "connection refused" in e or "could not resolve" in e or "name or service not known" in e:
        return SourceError("Không kết nối được tới máy chủ của link.", "SOURCE_UNREACHABLE", True)
    if "invalid data found" in e or "moov atom not found" in e or "end of file" in e:
        return SourceError("File hỏng hoặc không phải file video/audio.", "NOT_MEDIA")
    if "no such file" in e:
        return SourceError("Không tìm thấy file.", "SOURCE_NOT_FOUND")
    if "protocol not found" in e or "unsupported protocol" in e:
        return SourceError("Định dạng link không được hỗ trợ.", "UNSUPPORTED_URL")
    last = stderr.strip().splitlines()[-1][:300] if stderr.strip() else "ffmpeg lỗi"
    return SourceError("ffmpeg không đọc được nguồn: " + last, "NOT_MEDIA")


def probe_media(src, require_audio: bool = True) -> dict:
    """Kiểm tra nguồn trước khi xử lý: đọc được không, có kênh âm thanh không, có quá dài không."""
    cmd = ["ffprobe", "-v", "error", *(_net_opts(src)[:2]), "-show_entries", "format=duration:stream=codec_type",
           "-of", "json", str(src)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=NET_TIMEOUT_SEC + 15)
    except subprocess.TimeoutExpired:
        raise SourceError("Hết thời gian chờ khi đọc nguồn video (timeout)", "SOURCE_TIMEOUT", True)
    if r.returncode != 0:
        raise _ffmpeg_error(r.stderr, src)
    import json as _json
    info = _json.loads(r.stdout or "{}")
    types = [st.get("codec_type") for st in info.get("streams", [])]
    if not types:
        raise SourceError("File hỏng hoặc không phải file video/audio.", "NOT_MEDIA")
    if require_audio and "audio" not in types:
        raise SourceError("Nguồn không có kênh âm thanh – không thể nhận dạng lời thoại. "
                          "Hãy tải kèm file phụ đề .srt/.vtt.", "NO_AUDIO")
    try:
        dur = float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        dur = None
    if dur and dur > MAX_DURATION_MIN * 60:
        raise SourceError(f"Video dài {dur / 60:.0f} phút, vượt giới hạn {MAX_DURATION_MIN:.0f} phút (MAX_DURATION_MIN).",
                          "TOO_LONG")
    return {"duration": round(dur, 3) if dur else None, "streams": types}


def extract_audio(src: str | Path, out_wav: Path) -> Path:
    """ffmpeg → WAV 16 kHz mono (đầu vào chuẩn cho ASR). Hỗ trợ file, link mp4/webm, HLS (.m3u8)."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *_net_opts(src), "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
           "-c:a", "pcm_s16le", str(out_wav)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=MAX_DURATION_MIN * 60)
    except subprocess.TimeoutExpired:
        raise SourceError("Tách audio quá lâu (timeout)", "SOURCE_TIMEOUT", True)
    if r.returncode != 0 or not out_wav.exists() or out_wav.stat().st_size < 1000:
        raise _ffmpeg_error(r.stderr, src)
    return out_wav


MAX_DOWNLOAD_MB = float(__import__("os").getenv("MAX_DOWNLOAD_MB", "2048"))


def download_media(url: str, dest_dir: Path) -> Path:
    """Tải link file media (mp4/webm/mp3…) về đĩa trước khi xử lý: không phụ thuộc máy chủ có hỗ trợ
    HTTP Range hay không, báo lỗi HTTP rõ ràng, giới hạn dung lượng. (Link .m3u8 để ffmpeg đọc trực tiếp.)"""
    import urllib.error
    import urllib.request
    ext = Path(urlparse(url).path).suffix.lower() or ".mp4"
    dest = dest_dir / f"source{ext}"
    req = urllib.request.Request(url, headers={"User-Agent": "cnweb-transcript/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=NET_TIMEOUT_SEC) as r, open(dest, "wb") as f:
            total = 0
            while chunk := r.read(1 << 20):
                total += len(chunk)
                if total > MAX_DOWNLOAD_MB * (1 << 20):
                    raise SourceError(f"File lớn hơn {MAX_DOWNLOAD_MB:.0f} MB (MAX_DOWNLOAD_MB).", "TOO_LARGE")
                f.write(chunk)
    except urllib.error.HTTPError as e:
        code = {404: "SOURCE_NOT_FOUND", 401: "SOURCE_FORBIDDEN", 403: "SOURCE_FORBIDDEN"}.get(e.code, "SOURCE_ERROR")
        raise SourceError(f"Không tải được link (HTTP {e.code}).", code, retryable=e.code >= 500) from e
    except urllib.error.URLError as e:
        raise SourceError(f"Không kết nối được tới máy chủ của link ({e.reason}).", "SOURCE_UNREACHABLE", True) from e
    except TimeoutError as e:
        raise SourceError("Hết thời gian chờ khi tải link.", "SOURCE_TIMEOUT", True) from e
    return dest


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
        msg = str(e)
        if "Unsupported URL" in msg:
            raise SourceError("Trang này không có video mà tool đọc được (yt-dlp: Unsupported URL). "
                              "Hãy dán link trực tiếp tới file video hoặc link YouTube.", "UNSUPPORTED_URL") from e
        if "HTTP Error 404" in msg:
            raise SourceError("Không tìm thấy trang video (HTTP 404).", "SOURCE_NOT_FOUND") from e
        if "Private video" in msg or "unavailable" in msg.lower():
            raise SourceError("Video không còn hoặc để riêng tư.", "SOURCE_UNAVAILABLE") from e
        raise SourceError(f"Không đọc được thông tin video: {msg[-300:]}", "SOURCE_ERROR",
                          retryable="timed out" in msg.lower()) from e


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
