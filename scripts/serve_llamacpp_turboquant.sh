#!/usr/bin/env bash
# Serve a GGUF model with TurboQuant-equivalent settings via llama-cpp-python.
#
# "TurboQuant" profile = IQ4_XS weights + 8-bit KV cache:
#   - IQ4_XS GGUF: importance-matrix 4-bit quantisation (~4.25 bpw)
#     preserves quality better than Q4_K_M at similar or smaller VRAM
#   - --cache-type-k q8_0: 8-bit K cache (halves KV VRAM vs FP16, minimal loss)
#   - --cache-type-v q8_0: 8-bit V cache
#   - --flash-attn: fused attention kernel (faster + lower peak VRAM)
#
# On RTX 4070 (8 GB):
#   IQ4_XS 7B weights ≈ 4.5 GB  +  q8_0 KV @ ctx=8192 ≈ 0.6 GB  +  overhead ≈ 0.5 GB
#   Total ≈ 5.6 GB — leaves ~2.4 GB headroom for batch processing.
#
# Requirements:
#   pip install "llama-cpp-python[cuda]" --extra-index-url \
#     https://abetlen.github.io/llama-cpp-python/whl/cu121
#
# Environment variables (override defaults):
#   MODEL_PATH   — path to the IQ4_XS .gguf file
#   N_GPU_LAYERS — layers to offload (default: -1 = all)
#   CTX_SIZE     — context window (default: 8192)
#   N_THREADS    — CPU threads (default: 4)
#   HOST         — bind address (default: 0.0.0.0)
#   PORT         — listen port (default: 8080)

set -euo pipefail

MODEL_PATH="${MODEL_PATH:-models/Qwen2.5-Coder-7B-Instruct-IQ4_XS.gguf}"
N_GPU_LAYERS="${N_GPU_LAYERS:--1}"
CTX_SIZE="${CTX_SIZE:-8192}"
N_THREADS="${N_THREADS:-4}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"

if [[ $# -ge 1 ]]; then
  MODEL_PATH="$1"
fi

if [[ ! -f "$MODEL_PATH" ]]; then
  echo "ERROR: IQ4_XS model not found at $MODEL_PATH"
  echo ""
  echo "Download with:"
  echo "  huggingface-cli download bartowski/Qwen2.5-Coder-7B-Instruct-GGUF \\"
  echo "    Qwen2.5-Coder-7B-Instruct-IQ4_XS.gguf --local-dir models/"
  echo ""
  echo "Or quantise from FP16 yourself:"
  echo "  ./llama-quantize Qwen2.5-Coder-7B-Instruct-F16.gguf \\"
  echo "    models/Qwen2.5-Coder-7B-Instruct-IQ4_XS.gguf IQ4_XS"
  exit 1
fi

echo "==> Starting llama-cpp-python server (TurboQuant profile)"
echo "    model:       $MODEL_PATH"
echo "    gpu_layers:  $N_GPU_LAYERS"
echo "    ctx_size:    $CTX_SIZE"
echo "    kv_cache:    q8_0 (8-bit K + V — halves KV VRAM vs FP16)"
echo "    flash_attn:  enabled"
echo "    endpoint:    http://$HOST:$PORT/v1/chat/completions"
echo ""

python -m llama_cpp.server \
  --model "$MODEL_PATH" \
  --n_gpu_layers "$N_GPU_LAYERS" \
  --n_ctx "$CTX_SIZE" \
  --n_threads "$N_THREADS" \
  --host "$HOST" \
  --port "$PORT" \
  --chat_format chatml \
  --cache_type_k q8_0 \
  --cache_type_v q8_0 \
  --flash_attn true \
  --verbose false
