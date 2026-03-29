#!/bin/bash
# Start SGLang server for Mercer on RTX 4070
python -m sglang.launch_server \
  --model-path Qwen/Qwen2.5-Coder-7B-Instruct \
  --dtype bfloat16 \
  --quantization fp8 \
  --enable-cuda-graph \
  --enable-flashinfer \
  --mem-fraction-static 0.88 \
  --context-length 16384 \
  --port 30000
