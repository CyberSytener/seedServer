"""X-Request-ID middleware — ensures every request/response carries a trace ID.

If an incoming request already contains an ``X-Request-ID`` header the value
is preserved.  Otherwise a random UUID-4 is generated.  The ID is:

* stored on ``request.state.request_id`` for handler/log access, and
* set as the ``X-Request-ID`` response header.
"""

from __future__ import annotations

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[a-zA-Z0-9._-]{1,128}$")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject or forward *X-Request-ID* on every HTTP exchange."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        raw = (request.headers.get(_HEADER) or "").strip()
        # Only accept well-formed IDs to prevent header/log injection
        if raw and _VALID_REQUEST_ID.match(raw):
            request_id = raw
        else:
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        response: Response = await call_next(request)
        response.headers[_HEADER] = request_id
        return response
