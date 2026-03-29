"""kernels — GPU acceleration layer for Mercer.

CUDA/Triton kernels for LSH hashing, tokenization, and candidate scoring.
Every kernel has a CPU fallback so the pipeline runs without a GPU.

Exports:
    CUDA_AVAILABLE  bool — True when torch + CUDA are present and usable.
    USE_GPU         bool — Alias for CUDA_AVAILABLE; controls kernel dispatch.
"""

from __future__ import annotations

from core.logging import get_logger

_logger = get_logger(__name__)

try:
    import torch as _torch
    CUDA_AVAILABLE: bool = _torch.cuda.is_available()
except ImportError:
    CUDA_AVAILABLE = False

USE_GPU: bool = CUDA_AVAILABLE

if USE_GPU:
    _logger.info("GPU kernels active", cuda_device=_torch.cuda.get_device_name(0))
else:
    _logger.info("GPU unavailable, using CPU fallbacks")

__all__ = ["CUDA_AVAILABLE", "USE_GPU"]
