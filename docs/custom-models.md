# Using Custom Models with Mercer

Mercer's inference layer is fully pluggable. This guide covers three scenarios:

1. Swapping to a different model on SGLang (local serving)
2. Switching to a different cloud API provider (Gemini, Mistral, etc.)
3. Writing a new `LLMBackend` implementation for any other inference system

---

## 1. Swapping Models on SGLang

SGLang serves any HuggingFace-compatible causal LM. The only requirement is that the model follows the OpenAI chat completions format (which SGLang provides automatically).

### Default: Qwen2.5-Coder-7B-Instruct

```bash
python -m sglang.launch_server \
  --model-path Qwen/Qwen2.5-Coder-7B-Instruct \
  --dtype bfloat16 \
  --quantization fp8 \
  --enable-cuda-graph \
  --enable-flashinfer \
  --mem-fraction-static 0.88 \
  --port 30000
```

### Larger model: Qwen2.5-Coder-32B-Instruct (requires A100/H100)

```bash
python -m sglang.launch_server \
  --model-path Qwen/Qwen2.5-Coder-32B-Instruct \
  --dtype bfloat16 \
  --tensor-parallel-size 2 \
  --enable-cuda-graph \
  --enable-flashinfer \
  --port 30000
```

Set `SGLANG_URL=http://localhost:30000` in `.env`. No code changes needed — the SGLang backend talks to whatever model is being served on that port.

### Other code-specialized models

Any instruction-tuned model that follows the chat template convention works:

```bash
# DeepSeek-Coder-V2-Instruct
python -m sglang.launch_server \
  --model-path deepseek-ai/DeepSeek-Coder-V2-Instruct \
  --dtype bfloat16 \
  --port 30000

# StarCoder2-15B-Instruct
python -m sglang.launch_server \
  --model-path bigcode/starcoder2-15b-instruct-v0.1 \
  --dtype bfloat16 \
  --port 30000
```

### Updating the model name in config

When you change models, update `config/inference.yaml` so the audit log reflects the correct model name:

```yaml
# config/inference.yaml
sglang:
  model: "Qwen/Qwen2.5-Coder-32B-Instruct"   # displayed in audit log
  base_url: "http://localhost:30000"
  temperature: 0.0
  max_tokens: 2048
```

The `_model` attribute on `SGLangBackend` is used only for the audit log — it doesn't control which model SGLang loads.

---

## 2. Using a Different API Provider

Mercer ships with `AnthropicBackend` and `OpenAIBackend`. The model router selects between them based on `INFERENCE_BACKEND`.

### Switching to OpenAI

```bash
# .env
INFERENCE_BACKEND=openai
OPENAI_API_KEY=sk-...
```

To change the model, edit `config/inference.yaml`:

```yaml
openai:
  model: "gpt-4o"
  temperature: 0.0
  max_tokens: 2048
```

### Using Gemini via OpenAI-compatible endpoint

Google's Gemini API exposes an OpenAI-compatible endpoint. Use `OpenAIBackend` with a custom base URL:

```python
# In your .env / environment
OPENAI_API_KEY=your-gemini-api-key
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
```

Then extend `config/settings.py` to pass `base_url` to the client:

```python
# config/settings.py
openai_base_url: str = ""   # empty = default OpenAI URL
```

```python
# inference/api_backend.py — OpenAIBackend.__init__
self._client = openai.AsyncOpenAI(
    api_key=...,
    base_url=settings.openai_base_url or None,
)
```

### Using Mistral API

Mistral exposes an OpenAI-compatible API. Same approach as Gemini — use `OpenAIBackend` with `base_url=https://api.mistral.ai/v1`.

---

## 3. Adding a New LLMBackend

The backend protocol is defined in `inference/base.py`:

```python
class LLMBackend(Protocol):
    async def generate(
        self,
        prompt: str,
        system: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str: ...

    async def generate_batch(
        self,
        prompts: list[str],
        system: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> list[str]: ...
```

### Step-by-step: add a Cohere backend

**1. Create `inference/cohere_backend.py`:**

```python
"""Cohere async backend."""

from __future__ import annotations

import cohere

from config.settings import settings
from inference.base import LLMBackend


class CohereBackend(LLMBackend):
    """Async Cohere backend using the Chat API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._model = model or "command-r-plus"
        self._client = cohere.AsyncClientV2(
            api_key=api_key or settings.cohere_api_key
        )

    async def generate(
        self,
        prompt: str,
        system: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """Generate a completion using the Cohere Chat API."""
        response = await self._client.chat(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.message.content[0].text
```

**2. Add the API key to `config/settings.py`:**

```python
cohere_api_key: str = ""
```

**3. Register it in `inference/router.py`:**

```python
from inference.cohere_backend import CohereBackend

# In ModelRouter._build_api_backend():
if settings.inference_backend == "cohere":
    return CohereBackend()
```

**4. Set `INFERENCE_BACKEND=cohere` in `.env`.**

### What `generate()` must guarantee

- Returns a plain string (the model's text output only — no role markers, no JSON wrapper)
- Strips any `<thinking>...</thinking>` blocks if the model emits extended reasoning (see `api_backend.py` for the pattern)
- Never raises on rate-limit errors — retry internally (use `tenacity` as shown in `api_backend.py`)
- Is safe to call concurrently from `asyncio.gather()` (stateless per-call)

### Batch generation

The default `generate_batch()` in `LLMBackend` fans out to `generate()` via `asyncio.gather()`. Override it only if the API has a true batch endpoint:

```python
async def generate_batch(
    self,
    prompts: list[str],
    system: str,
    temperature: float = 0.0,
    max_tokens: int = 2048,
) -> list[str]:
    """Use Cohere's native batch endpoint."""
    # ... native batch call
```

### Testing your backend

Add a test file `tests/test_cohere_backend.py` following the pattern in `tests/test_sglang_backend.py` — mock the HTTP client, verify the payload shape, test health check. Do not hit real APIs in unit tests.
