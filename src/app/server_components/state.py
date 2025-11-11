from __future__ import annotations

import asyncio
from typing import Any

# Track callback payloads received from downstream AI webhooks.
callback_messages: list[dict[str, Any]] = []

# Hold pending asyncio queues per session for OpenAI-compatible streaming.
pending_responses: dict[str, asyncio.Queue] = {}

__all__ = ["callback_messages", "pending_responses"]
