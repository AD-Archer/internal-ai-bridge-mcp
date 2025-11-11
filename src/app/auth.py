"""Authentication helpers for Starlette apps."""

from __future__ import annotations

from typing import Sequence

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BearerAuthMiddleware:
    """ASGI middleware that enforces Bearer auth on HTTP and WebSocket routes."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        enabled: bool = False,
        default_token: str | None = None,
        route_tokens: dict[str, str] | None = None,
        exempt_paths: Sequence[str] | None = None,
    ) -> None:
        self.app = app
        self.enabled = enabled
        self.default_token = default_token
        self.exempt_paths = {self._normalize_path(path) for path in (exempt_paths or [])}
        self.route_tokens = self._prepare_route_tokens(route_tokens or {})

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        return path or "/"

    def _prepare_route_tokens(self, route_tokens: dict[str, str]) -> list[tuple[str, str]]:
        """Return a list of (prefix, token) sorted by longest prefix first."""
        normalized: list[tuple[str, str]] = []
        for raw_prefix, token in route_tokens.items():
            if not token:
                continue
            prefix = self._normalize_path(raw_prefix)
            normalized.append((prefix, token))
        # Longest prefix first so more specific routes win.
        normalized.sort(key=lambda item: len(item[0]), reverse=True)
        return normalized

    def _match_route_token(self, path: str) -> str | None:
        cleaned_path = self._normalize_path(path or "/")
        for prefix, token in self.route_tokens:
            if prefix == "/":
                return token
            if cleaned_path == prefix or cleaned_path.startswith(f"{prefix}/"):
                return token
        return None

    @staticmethod
    def _get_header(scope: Scope, key: bytes) -> str | None:
        for name, value in scope.get("headers", []):
            if name == key:
                return value.decode("latin-1")
        return None

    @staticmethod
    def _is_authorized(header_value: str | None, expected_token: str) -> bool:
        if not header_value:
            return False
        scheme, _, token = header_value.partition(" ")
        if not token:
            # Support passing only the token for convenience, though clients should include "Bearer".
            token = scheme
            scheme = "Bearer"
        return scheme.lower() == "bearer" and token == expected_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")
        normalized_path = self._normalize_path(path)
        if normalized_path in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        required_token = self._match_route_token(path) or self.default_token
        if not required_token:
            await self.app(scope, receive, send)
            return

        header_value = self._get_header(scope, b"authorization")
        if self._is_authorized(header_value, required_token):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "http":
            response = JSONResponse(
                {"error": "Unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        # WebSocket: emit policy violation close (1008).
        close_message: Message = {
            "type": "websocket.close",
            "code": 1008,
            "reason": "Unauthorized",
        }
        await send(close_message)


__all__ = ["BearerAuthMiddleware"]
