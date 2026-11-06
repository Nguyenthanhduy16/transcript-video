#!/usr/bin/env bash
# Tải model chạy trên CPU (sherpa-onnx) vào ./models – không cần GPU hay HuggingFace token.
#   ReazonSpeech zipformer (ASR tiếng Nhật, ~160 MB int8), Silero VAD,
#   GTCRN (khử nhiễu), 3D-Speaker ERes2Net (embedding người nói). Tuỳ chọn: Whisper small (--whisper).
set -euo pipefail
cd "$(dirname "$0")/.." && mkdir -p models && cd models
REL=https://github.com/k2-fsa/sherpa-onnx/releases/download
get() { curl -fsSL "$REL/$1.tar.bz2" | tar -xjf - --wildcards "${@:2}"; }
[ -d sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01 ] || \
  get asr-models/sherpa-onnx-zipformer-ja-reazonspeech-2024-08-01 '*int8*' '*tokens.txt'
[ -f silero_vad.onnx ] || curl -fsSL -o silero_vad.onnx "$REL/asr-models/silero_vad.onnx"
[ -f gtcrn_simple.onnx ] || curl -fsSL -o gtcrn_simple.onnx "$REL/speech-enhancement-models/gtcrn_simple.onnx"
[ -f 3dspeaker_eres2net_base.onnx ] || curl -fsSL -o 3dspeaker_eres2net_base.onnx \
  "$REL/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
if [ "${1:-}" = "--whisper" ] && [ ! -d sherpa-onnx-whisper-small ]; then
  get asr-models/sherpa-onnx-whisper-small '*int8*' '*tokens.txt'
fi
ls -la
