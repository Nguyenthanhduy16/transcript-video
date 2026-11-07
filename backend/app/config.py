"""Cấu hình đọc từ biến môi trường."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
VIDEOS_DIR = DATA_DIR / "videos"      # transcript JSON
JOBS_DIR = DATA_DIR / "jobs"          # trạng thái job
MEDIA_DIR = DATA_DIR / "media"        # audio/video tải về hoặc upload
FRONTEND_DIR = ROOT / "frontend"

for d in (VIDEOS_DIR, JOBS_DIR, MEDIA_DIR):
    d.mkdir(parents=True, exist_ok=True)

# LLM (Claude) – dịch + phân tích. LLM_PROVIDER=none để chạy offline.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
# LLM_PROFILE: quality = một model cho cả dịch + phân tích (mặc định Opus 5.5);
#              economy = dịch bằng Sonnet 5.5, phân tích từ vựng/ngữ pháp bằng Haiku 5.5, effort low
#              (ước tính ~0,3–0,6 USD/tập 50 phút – xem docs/nghiem-thu-P1.md)
LLM_PROFILE = os.getenv("LLM_PROFILE", "quality")
_ECON = LLM_PROFILE == "economy"
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5-5" if _ECON else "claude-opus-5-5")          # model dịch
LLM_ANALYSIS_MODEL = os.getenv("LLM_ANALYSIS_MODEL", "claude-haiku-5-5" if _ECON else LLM_MODEL)  # model phân tích
LLM_EFFORT = os.getenv("LLM_EFFORT", "low" if _ECON else "medium")
LLM_BATCH_SIZE = int(os.getenv("LLM_BATCH_SIZE", "30"))      # 20–50 cue/lô
LLM_CONTEXT_BEFORE = int(os.getenv("LLM_CONTEXT_BEFORE", "6"))
LLM_CONTEXT_AFTER = int(os.getenv("LLM_CONTEXT_AFTER", "3"))

# ASR
MODELS_DIR = Path(os.getenv("MODELS_DIR", ROOT / "models"))   # scripts/download_models.sh
# auto = ReazonSpeech (sherpa-onnx, CPU) nếu đã tải model, ngược lại faster-whisper
ASR_ENGINE = os.getenv("ASR_ENGINE", "auto")   # auto | reazon | whisper-onnx | faster-whisper | whisperx
ASR_THREADS = int(os.getenv("ASR_THREADS", str(min(8, os.cpu_count() or 4))))
# Khử nhiễu GTCRN (nhạc nền, ồn): auto = chỉ khi VAD trên audio gốc thấy ồn liên tục;
# vad = luôn khử nhiễu để cắt câu (nhận dạng trên audio gốc); both = cắt câu + nhận dạng trên audio đã khử nhiễu; off
ASR_DENOISE = os.getenv("ASR_DENOISE", "vad")
ASR_MODEL = os.getenv("ASR_MODEL", "large-v3")
ASR_DEVICE = os.getenv("ASR_DEVICE", "auto")              # auto | cpu | cuda
ASR_COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "default")

# Người nói: auto = gom cụm embedding 3D-Speaker theo từng câu (CPU, không cần token);
# pyannote chỉ dùng khi DIARIZE=pyannote và có HF_TOKEN.
DIARIZE = os.getenv("DIARIZE", "auto")   # auto | embedding | pyannote | off
DIARIZE_THRESHOLD = float(os.getenv("DIARIZE_THRESHOLD", "0.5"))  # khoảng cách cosine để tách cụm
HF_TOKEN = os.getenv("HF_TOKEN", "")

# Chia cue
CUE_MIN_SEC = 1.0
CUE_MAX_SEC = 7.0
CUE_MAX_CHARS = 32          # ~2 dòng × 16 ký tự tiếng Nhật
CUE_MAX_CHARS_LATIN = 84    # ~2 dòng × 42 ký tự (tiếng Anh…)
SUPPORTED_LANGS = ("ja", "en")


def max_chars_for(lang: str) -> int:
    return CUE_MAX_CHARS if lang in ("ja", "zh", "ko") else CUE_MAX_CHARS_LATIN
CUE_PAUSE_SPLIT_SEC = 0.6
