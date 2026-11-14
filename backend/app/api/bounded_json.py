"""Bound request bodies before FastAPI parses mutation JSON."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request
from fastapi.routing import APIRoute
from starlette.responses import Response

from app.core.auth import AuthDenied


class BoundedJSONRoute(APIRoute):
    max_body_bytes = 4096
    methods_with_body = frozenset({"POST"})
    invalid_headers_code = "INVALID_REVIEW_HEADERS"
    too_large_code = "REVIEW_BODY_TOO_LARGE"

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def bounded(request: Request) -> Response:
            if request.method not in self.methods_with_body:
                return await handler(request)

            lengths = request.headers.getlist("content-length")
            media_types = request.headers.getlist("content-type")
            encodings = request.headers.getlist("content-encoding")
            if (
                len(lengths) > 1
                or len(media_types) != 1
                or media_types[0].split(";", 1)[0].strip().lower() != "application/json"
                or len(encodings) > 1
                or encodings and encodings[0].lower() != "identity"
            ):
                raise AuthDenied(self.invalid_headers_code, 422)
            if lengths:
                declared = lengths[0]
                if not declared.isascii() or not declared.isdigit():
                    raise AuthDenied("INVALID_CONTENT_LENGTH", 422)
                # Avoid integer conversion of attacker-sized decimal strings.
                canonical = declared.lstrip("0") or "0"
                maximum = str(self.max_body_bytes)
                if len(canonical) > len(maximum) or (
                    len(canonical) == len(maximum) and canonical > maximum
                ):
                    raise AuthDenied(self.too_large_code, 422)

            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > self.max_body_bytes:
                    raise AuthDenied(self.too_large_code, 422)
                body.extend(chunk)
            # FastAPI reads Request.body(); cache only the bounded stream.
            request.__dict__["_body"] = bytes(body)
            return await handler(request)

        return bounded
