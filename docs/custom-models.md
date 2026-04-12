# Using Custom Models with Mercer

Mercer's inference layer is fully pluggable. This guide covers four scenarios:

1. Swapping to a different GGUF model for llama.cpp (local serving)
2. Using the TurboQuant profile — IQ4_XS + q8_0 KV cache for VRAM-constrained GPUs
3. Switching to a different cloud API provider (Gemini, Mistral, etc.)
4. Writing a new `LLMBackend` implementation for any other inference system

---

## GPU Memory Quick Reference

| Model | Quantization | Weights | KV (8K ctx) | Total | Fits 8 GB? |
|---|---|---|---|---|---|
| Qwen2.5-Coder-7B | Q4_K_M | 4.8 GB | 1.2 GB (f16) | **6.0 GB** | ✅ |
| Qwen2.5-Coder-7B | IQ4_XS + q8_0 KV | 4.5 GB | 0.6 GB | **5.1 GB** | ✅ (TurboQuant) |
| Qwen2.5-Coder-7B | IQ3_XS + q8_0 KV | 3.6 GB | 0.6 GB | **4.2 GB** | ✅ (max headroom) |
| Qwen2.5-Coder-7B | Q6_K + q4_0 KV | 6.5 GB | 0.3 GB | **6.8 GB** | ✅ (near-lossless) |

---

## 1. Swapping Models on llama.cpp

All models must be in GGUF format. `bartowski` on HuggingFace provides GGUF builds for most popular models.

### Qwen2.5-Coder-7B — Recommended GGUF builds

```bash
# IQ4_XS — best quality-per-VRAM (TurboQuant default)
huggingface-cli download bartowski/Qwen2.5-Coder-7B-Instruct-GGUF \
  Qwen2.5-Coder-7B-Instruct-IQ4_XS.gguf --local-dir models/

# Q4_K_M — common community choice, slightly larger
huggingface-cli download bartowski/Qwen2.5-Coder-7B-Instruct-GGUF \
  Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf --local-dir models/
```

Start with the TurboQuant script:

```bash
MODEL_PATH=models/Qwen2.5-Coder-7B-Instruct-IQ4_XS.gguf \
  bash scripts/serve_llamacpp_turboquant.sh
```

### Larger model: Qwen2.5-Coder-14B (requires 12+ GB VRAM)

```bash
huggingface-cli download bartowski/Qwen2.5-Coder-14B-Instruct-GGUF \
  Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf --local-dir models/

MODEL_PATH=models/Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf \
  bash scripts/serve_llamacpp.sh
```

Set `LLAMACPP_URL=http://localhost:8080` in `.env`. No code changes needed — `LlamaCppBackend` ignores the model field and talks to whatever is loaded.

---

## 2. TurboQuant Profile

TurboQuant is a llama.cpp configuration that maximises VRAM efficiency on 8 GB GPUs:

- **IQ4_XS weights** — importance-matrix 4-bit quantisation, better quality than Q4_K_M at similar size
- **q8_0 KV cache** — `--cache-type-k q8_0 --cache-type-v q8_0` halves KV VRAM vs FP16
- **Flash attention** — `--flash-attn` reduces peak VRAM during attention computation

```bash
bash scripts/serve_llamacpp_turboquant.sh
```

**VRAM budget (RTX 4070, 8 GB):**
- IQ4_XS weights: ~4.5 GB
- q8_0 KV @ ctx=8192: ~0.6 GB
- Overhead: ~0.5 GB
- **Total: ~5.6 GB** — 2.4 GB headroom

---

## 3. Cloud API Providers

Set `INFERENCE_BACKEND` to switch from local to cloud:

```bash
# Anthropic (default cloud fallback)
INFERENCE_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
INFERENCE_BACKEND=openai
OPENAI_API_KEY=sk-...
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

    async def generate_batch(self, prompts: list[str], system: str, **kwargs) -> list[str]:
        import asyncio
        return list(await asyncio.gather(*(
            self.generate(p, system, **kwargs) for p in prompts
        )))

    async def health_check(self) -> bool:
        return True  # API backends are assumed healthy
```

Wire it into `inference/router.py`'s `_get_api_backend()` and add a `gemini_api_key` field to `config/settings.py`.

---

## 4. Writing a New LLMBackend

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
        temperature: float = 0.0,
        max_tokens: int = 1024,
        is_json: bool = False,
    ) -> list[str]: ...

    async def health_check(self) -> bool: ...
```

Key constraints:
- All methods must be `async`
- `generate_batch` should use `asyncio.gather` for concurrency
- `is_json=True` should request JSON output mode when the backend supports it
- `health_check` should be cheap (single HTTP probe, short timeout)
- Use `tenacity` for retry logic on transient HTTP errors

Add a test file `tests/test_<name>_backend.py` following the pattern in
`tests/test_api.py` — mock the HTTP client, verify the payload shape, test
health check. Do not hit real APIs in unit tests.
