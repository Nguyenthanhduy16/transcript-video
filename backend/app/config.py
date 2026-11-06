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
LLM_MODEL = os.getenv("LLM_MODEL", "claude-opus-5-5")
LLM_EFFORT = os.getenv("LLM_EFFORT", "medium")
LLM_BATCH_SIZE = int(os.getenv("LLM_BATCH_SIZE", "30"))      # 20–50 cue/lô
LLM_CONTEXT_BEFORE = int(os.getenv("LLM_CONTEXT_BEFORE", "6"))
LLM_CONTEXT_AFTER = int(os.getenv("LLM_CONTEXT_AFTER", "3"))

# ASR
ASR_ENGINE = os.getenv("ASR_ENGINE", "faster-whisper")   # faster-whisper | whisperx
ASR_MODEL = os.getenv("ASR_MODEL", "large-v3")
ASR_DEVICE = os.getenv("ASR_DEVICE", "auto")              # auto | cpu | cuda
ASR_COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "default")

# Diarization (pyannote) – cần HF_TOKEN đã chấp nhận điều khoản model
DIARIZE = os.getenv("DIARIZE", "auto")   # auto | on | off
HF_TOKEN = os.getenv("HF_TOKEN", "")

# Chia cue
CUE_MIN_SEC = 1.0
CUE_MAX_SEC = 7.0
CUE_MAX_CHARS = 32          # ~2 dòng × 16 ký tự tiếng Nhật
CUE_PAUSE_SPLIT_SEC = 0.6
