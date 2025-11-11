"""Client helper for talking to the in-house AI webhook backend."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import logging

logger = logging.getLogger(__name__)


class AIWebhookError(RuntimeError):
    """Raised when the webhook backend returns an error."""


class AIWebhookClient:
    """Thin wrapper around the HTTP webhook interface."""

    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout

    def _build_headers(self, extra: dict[str, str] | None = None, secret: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if secret:
            headers["X-Webhook-Secret"] = secret
        if extra:
            headers.update(extra)
        return headers

    @staticmethod
    def _handle_response(response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            logger.error("Backend returned error: %s %s", exc.response.status_code, body)
            raise AIWebhookError(f"Webhook call failed: {exc.response.status_code} {body}") from exc

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return {"status_code": response.status_code, "body": response.text}

    async def _make_request_with_retry(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make HTTP request with exponential backoff retry on 5xx errors."""
        max_retries = 3
        base_delay = 1.0
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(method, url, **kwargs)
                    # Retry on 5xx server errors
                    if response.status_code >= 500 and attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        await asyncio.sleep(delay)
                        continue
                    return response
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                raise AIWebhookError(f"Request failed after retries: {exc}") from exc
        # Should not reach here
        raise AIWebhookError("Unexpected retry logic error")

    async def start_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Trigger a new AI message via webhook."""
        response = await self._make_request_with_retry("POST", self.base_url, json=payload, headers=self._build_headers())
        return self._handle_response(response)

    async def trigger_webhook(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        secret: str | None = None,
    ) -> dict[str, Any]:
        """Call an arbitrary webhook endpoint."""
        method_upper = method.upper()
        response = await self._make_request_with_retry(
            method_upper,
            url,
            json=payload,
            headers=self._build_headers(headers, secret),
        )
        return self._handle_response(response)
