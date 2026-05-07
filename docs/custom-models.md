# Using Custom Models with Mercer

Mercer's inference layer is fully pluggable. This guide covers:

1. Why **Arctic-Text2SQL-R1-7B** is the recommended local default (and how to swap to it)
2. Falling back to Qwen2.5-Coder-7B if you've already got it
3. Using the TurboQuant profile — IQ4_XS + q8_0 KV cache for VRAM-constrained GPUs
4. Switching to a different cloud API provider (Gemini, Mistral, etc.)
5. Writing a new `LLMBackend` implementation for any other inference system

---

## 1. Recommended Local Model: Arctic-Text2SQL-R1-7B

The default GGUF Mercer ships with is **Snowflake's Arctic-Text2SQL-R1-7B**
(Apache 2.0). It's a Qwen2.5-Coder-7B-Instruct fine-tune trained with
execution-based reinforcement learning (GRPO) using only execution
correctness as the reward signal. It targets the exact task Mercer is
solving.

### Why this over the off-the-shelf Qwen baseline

| Model | BIRD-dev | Avg over 6 SQL benchmarks | VRAM (IQ4_XS + q8_0 KV) | License |
|---|---|---|---|---|
| **Arctic-Text2SQL-R1-7B** | **68.9%** | **57.2%** | ~5.4 GB | Apache 2.0 |
| Qwen2.5-Coder-7B-Instruct (off-the-shelf) | ~50% | ~45% | ~5.6 GB | Apache 2.0 |
| OmniSQL-7B | ~63% | 54.4% | ~5.6 GB | Apache 2.0 |
| DeepSeek-V3 (671B MoE) | ~68% | 55.6% | not feasible locally | DeepSeek License |

Same parameter count, same VRAM footprint, ~10pp accuracy gain on BIRD-dev
and consistent wins across the BIRD/Spider/EHRSQL/ScienceBenchmark suite.
The model card and paper are at
<https://huggingface.co/Snowflake/Arctic-Text2SQL-R1-7B>.

### Download and run

```bash
# Recommended: imatrix-quantised IQ4_XS (slightly better than static IQ4_XS
# at the same bit count, distributed by mradermacher).
huggingface-cli download mradermacher/Arctic-Text2SQL-R1-7B-i1-GGUF \
  Arctic-Text2SQL-R1-7B.i1-IQ4_XS.gguf --local-dir models/

# Rename to the canonical filename Mercer expects.
mv models/Arctic-Text2SQL-R1-7B.i1-IQ4_XS.gguf \
   models/Arctic-Text2SQL-R1-7B-IQ4_XS.gguf

# Start the server with the TurboQuant profile.
bash scripts/serve_llamacpp_turboquant.sh
```

The TurboQuant script reads `LOCAL_MODEL_PATH` from your `.env`. The default
in `.env.example` is already set to the Arctic path above, so you don't
need to override it.

### Static quants (no imatrix)

If you want the static quants instead of imatrix:

```bash
huggingface-cli download mradermacher/Arctic-Text2SQL-R1-7B-GGUF \
  Arctic-Text2SQL-R1-7B.IQ4_XS.gguf --local-dir models/
```

---

## 2. Falling Back to Qwen2.5-Coder-7B

If you already have `Qwen2.5-Coder-7B-Instruct-IQ4_XS.gguf` downloaded
locally and don't want to re-download, just point `LOCAL_MODEL_PATH` at it:

```bash
# In .env
LOCAL_MODEL_PATH=models/Qwen2.5-Coder-7B-Instruct-IQ4_XS.gguf
```

Or pass it via env var to the launcher:

```bash
LOCAL_MODEL_PATH=models/Qwen2.5-Coder-7B-Instruct-IQ4_XS.gguf \
  bash scripts/serve_llamacpp_turboquant.sh
```

No code changes needed. `LlamaCppBackend` ignores the model field in
requests and serves whatever is loaded.

### Larger Qwen variants (require 12+ GB VRAM)

```bash
huggingface-cli download bartowski/Qwen2.5-Coder-14B-Instruct-GGUF \
  Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf --local-dir models/

LOCAL_MODEL_PATH=models/Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf \
  bash scripts/serve_llamacpp.sh
```

---

## 3. GPU Memory Quick Reference

| Model | Quantization | Weights | KV (8K ctx) | Total | Fits 8 GB? |
|---|---|---|---|---|---|
| **Arctic-Text2SQL-R1-7B** | **IQ4_XS + q8_0 KV** | **4.25 GB** | **0.6 GB** | **~5.4 GB** | ✅ (recommended) |
| Qwen2.5-Coder-7B | Q4_K_M | 4.8 GB | 1.2 GB (f16) | ~6.0 GB | ✅ |
| Qwen2.5-Coder-7B | IQ4_XS + q8_0 KV | 4.5 GB | 0.6 GB | ~5.1 GB | ✅ (TurboQuant) |
| Qwen2.5-Coder-7B | IQ3_XS + q8_0 KV | 3.6 GB | 0.6 GB | ~4.2 GB | ✅ (max headroom) |
| Qwen2.5-Coder-7B | Q6_K + q4_0 KV | 6.5 GB | 0.3 GB | ~6.8 GB | ✅ (near-lossless) |
| Qwen2.5-Coder-14B | Q4_K_M | 8.4 GB | 2.4 GB | ~10.8 GB | ❌ (needs 12+ GB) |

---

## 4. TurboQuant Profile

TurboQuant is a llama.cpp configuration that maximises VRAM efficiency on
8 GB GPUs:

- **IQ4_XS weights** — importance-matrix 4-bit quantisation, better
  quality than Q4_K_M at similar size
- **q8_0 KV cache** — `--cache-type-k q8_0 --cache-type-v q8_0` halves
  KV VRAM vs FP16
- **Flash attention** — `--flash-attn` reduces peak VRAM during
  attention computation

```bash
bash scripts/serve_llamacpp_turboquant.sh
```

**VRAM budget on RTX 4070 (8 GB) with Arctic-Text2SQL-R1-7B:**

- IQ4_XS weights: ~4.25 GB
- q8_0 KV @ ctx=8192: ~0.6 GB
- Overhead: ~0.5 GB
- **Total: ~5.4 GB** — 2.6 GB headroom

---

## 5. Cloud API Providers

Set `INFERENCE_BACKEND` to switch from local to cloud:

```bash
# Anthropic (default cloud fallback)
INFERENCE_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
INFERENCE_BACKEND=openai
OPENAI_API_KEY=sk-...
```

The default Anthropic model is `claude-opus-4-7`. Override via the
`anthropic_model` setting if you want a different snapshot:

```bash
# In .env, but not surfaced in .env.example as it's an advanced option
ANTHROPIC_MODEL=claude-sonnet-4-6
```

### Adding a new provider (e.g. Gemini, Mistral)

Create `inference/gemini_backend.py`:

```python
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from inference.base import LLMBackend

class GeminiBackend(LLMBackend):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._api_key = api_key
        self._model = model
        self._client = httpx.AsyncClient(timeout=120.0)

    async def generate(self, prompt: str, system: str, temperature: float = 0.0,
                       max_tokens: int = 1024, is_json: bool = False) -> str:
        # Implement Gemini API call
        ...

    async def generate_batch(self, prompts: list[str], system: str,
                             temperature: float | list[float] = 0.0,
                             **kwargs) -> list[str]:
        from inference.base import _expand_temperatures
        import asyncio
        temps = _expand_temperatures(temperature, len(prompts))
        return list(await asyncio.gather(*(
            self.generate(p, system, temperature=t, **kwargs)
            for p, t in zip(prompts, temps)
        )))

    async def health_check(self) -> bool:
        return True  # API backends are assumed healthy
```

Wire it into `inference/router.py`'s `_get_api_backend()` and add a
`gemini_api_key` field to `config/settings.py`.

---

## 6. Writing a New LLMBackend

Every backend implements the protocol in `inference/base.py`:

```python
class LLMBackend(Protocol):
    async def generate(
        self,
        prompt: str,
        system: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        is_json: bool = False,
    ) -> str: ...

    async def generate_batch(
        self,
        prompts: list[str],
        system: str,
        temperature: float | list[float] = 0.0,
        max_tokens: int = 1024,
        is_json: bool = False,
    ) -> list[str]: ...

    async def health_check(self) -> bool: ...
```

Key constraints:
- All methods must be `async`
- `generate_batch` must accept `temperature` as either a scalar or a
  per-prompt list. Use `inference.base._expand_temperatures` to normalise
  it. The CHASE-SQL multi-candidate strategy depends on per-prompt
  temperatures (0.0 for direct_cot, 0.2 for divide_conquer, 0.3 for
  plan_execute) — collapsing to a single temperature kills the
  diversity signal.
- `is_json=True` should request JSON output mode when the backend supports it
- `health_check` should be cheap (single HTTP probe, short timeout)
- Use `tenacity` for retry logic on transient HTTP errors

Add a test file `tests/test_<name>_backend.py` following the pattern in
`tests/test_api.py` — mock the HTTP client, verify the payload shape, test
health check. Do not hit real APIs in unit tests.
