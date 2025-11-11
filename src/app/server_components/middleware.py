from __future__ import annotations

import logging
from typing import Set

from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from ..auth import BearerAuthMiddleware
from ..config import Settings

logger = logging.getLogger(__name__)


def build_auth_middleware(settings: Settings, *, exempt_paths: Set[str] | None = None) -> Middleware | None:
    """Configure bearer auth middleware if tokens exist."""
    if not settings.bearer_auth_enabled:
        return None

    tokens = {path: token for path, token in settings.route_bearer_tokens.items() if token}
    default_token = settings.default_bearer_token or None
    if not default_token and not tokens:
        logger.warning("Bearer auth is enabled but no tokens were configured; skipping middleware.")
        return None

    return Middleware(
        BearerAuthMiddleware,
        enabled=settings.bearer_auth_enabled,
        default_token=default_token,
        route_tokens=tokens,
        exempt_paths=sorted(exempt_paths or set()),
    )


def build_middleware(settings: Settings, *, exempt_paths: Set[str] | None = None) -> list[Middleware]:
    """Return the middleware stack shared across Starlette apps."""
    middleware: list[Middleware] = []
    auth_middleware = build_auth_middleware(settings, exempt_paths=exempt_paths)
    if auth_middleware:
        middleware.append(auth_middleware)
    middleware.append(
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    )
    return middleware


__all__ = ["build_auth_middleware", "build_middleware"]
