from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

import httpx

from ..config import Settings
from .state import callback_messages, pending_responses

logger = logging.getLogger(__name__)


def build_response_handler(settings: Settings) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """Create a coroutine that fans out recorded responses to listeners."""

    async def handle(record: dict[str, Any]) -> None:
        payload = dict(record.get("payload") or {})
        session_id = record.get("session_id")
        logger.info("🎯 Response handler called with: session_id=%s, payload=%s", session_id, payload)

        callback_messages.append(payload)
        logger.info("📝 Added to callback_messages, total count: %d", len(callback_messages))

        if session_id and session_id in pending_responses:
            logger.info("📋 Putting response in pending queue for session %s", session_id)
            await pending_responses[session_id].put(payload)
        elif session_id:
            logger.warning(
                "⚠️ Session %s not found in pending_responses. Keys: %s",
                session_id,
                list(pending_responses.keys()),
            )
        else:
            logger.warning("⚠️ No session_id in record")

        if settings.frontend_webhook_url:
            logger.info("🔗 Sending to frontend webhook: %s", settings.frontend_webhook_url)
            async with httpx.AsyncClient() as http_client:
                try:
                    response = await http_client.post(
                        str(settings.frontend_webhook_url),
                        json=payload,
                        timeout=200.0,
                    )
                    if response.status_code >= 400:
                        logger.error(
                            "❌ Frontend webhook %s returned %s: %s",
                            settings.frontend_webhook_url,
                            response.status_code,
                            response.text,
                        )
                    else:
                        logger.info(
                            "✅ Sent callback to frontend %s (status %s)",
                            settings.frontend_webhook_url,
                            response.status_code,
                        )
                except Exception as exc:  # pragma: no cover - network exception
                    logger.error("❌ Failed to send callback to frontend: %s", exc)
        else:
            logger.info("ℹ️ No frontend_webhook_url configured")

    return handle


__all__ = ["build_response_handler"]
