"""Simple API-key authentication middleware.

When VSAFE_API_KEY env var is set, all /api/* requests must include a matching
X-API-Key header. WebSocket and static/frontend routes are exempt.
"""

import logging
import os

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("VSAFE_API_KEY", "")


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not API_KEY:
            return await call_next(request)

        path = request.url.path

        if not path.startswith("/api/"):
            return await call_next(request)

        key = request.headers.get("X-API-Key", "")
        if key != API_KEY:
            return JSONResponse(
                status_code=401,
                content={"status": "error", "message": "Invalid or missing API key"},
            )

        return await call_next(request)


def check_ws_api_key(headers) -> bool:
    """Validate API key for WebSocket upgrade requests."""
    if not API_KEY:
        return True
    return headers.get("x-api-key", "") == API_KEY
