#!/usr/bin/env bash
# Serve a GGUF model via llama-cpp-python (OpenAI-compatible API on :8080).
#
# Usage:
#   bash scripts/serve_llamacpp.sh [path/to/model.gguf]
#
# Defaults to Q4_K_M quantisation — good balance of quality and VRAM.
# For 8 GB GPU (e.g. RTX 4070): Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf fits
# comfortably with room for KV cache.
#
# Requirements:
#   pip install "llama-cpp-python[cuda]" --extra-index-url \
#     https://abetlen.github.io/llama-cpp-python/whl/cu121
#
# Environment variables (override defaults):
#   LOCAL_MODEL_PATH or MODEL_PATH — path to the .gguf file
#                  (LOCAL_MODEL_PATH takes precedence; matches the
#                  Settings.local_model_path field in config/settings.py)
#   N_GPU_LAYERS — number of layers to offload to GPU (default: -1 = all)
#   CTX_SIZE     — context window size in tokens (default: 8192)
#   N_THREADS    — CPU threads for non-GPU work (default: 4)
#   HOST         — bind address (default: 0.0.0.0)
#   PORT         — listen port (default: 8080)

set -euo pipefail

DEFAULT_MODEL="models/Arctic-Text2SQL-R1-7B-IQ4_XS.gguf"

MODEL_PATH="${LOCAL_MODEL_PATH:-${MODEL_PATH:-$DEFAULT_MODEL}}"
N_GPU_LAYERS="${N_GPU_LAYERS:--1}"
CTX_SIZE="${CTX_SIZE:-8192}"
N_THREADS="${N_THREADS:-4}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"

# Allow positional override: serve_llamacpp.sh path/to/model.gguf
if [[ $# -ge 1 ]]; then
  MODEL_PATH="$1"
fi

if [[ ! -f "$MODEL_PATH" ]]; then
  echo "ERROR: model not found at $MODEL_PATH"
  echo ""
  echo "Recommended (best Text-to-SQL accuracy at 8 GB VRAM):"
  echo "  huggingface-cli download mradermacher/Arctic-Text2SQL-R1-7B-i1-GGUF \\"
  echo "    Arctic-Text2SQL-R1-7B.i1-IQ4_XS.gguf --local-dir models/"
  echo ""
  echo "Fallback (general-purpose Qwen2.5-Coder baseline):"
  echo "  huggingface-cli download bartowski/Qwen2.5-Coder-7B-Instruct-GGUF \\"
  echo "    Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf --local-dir models/"
  exit 1
fi

echo "==> Starting llama-cpp-python server"
echo "    model:       $MODEL_PATH"
echo "    gpu_layers:  $N_GPU_LAYERS"
echo "    ctx_size:    $CTX_SIZE"
echo "    endpoint:    http://$HOST:$PORT/v1/chat/completions"
echo ""

.venv/bin/python3 -m llama_cpp.server \
  --model "$MODEL_PATH" \
  --n_gpu_layers "$N_GPU_LAYERS" \
  --n_ctx "$CTX_SIZE" \
  --n_threads "$N_THREADS" \
  --host "$HOST" \
  --port "$PORT" \
  --chat_format chatml \
  --verbose false
