"""Optional API-key authentication.

If ``MERCER_API_KEY`` is set in the environment, every request must supply a
matching ``X-API-Key`` header. When the variable is unset the dependency is a
no-op and all requests are allowed through.
"""

from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from config.settings import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key(api_key: str | None = Security(_api_key_header)) -> None:
    """FastAPI dependency — validates the X-API-Key header when configured."""
    configured = settings.mercer_api_key
    if not configured:
        return  # Auth not configured — allow everything
    if api_key != configured:
        raise HTTPException(
            status_code=403,
            detail="Invalid or missing API key. Supply a valid X-API-Key header.",
        )
