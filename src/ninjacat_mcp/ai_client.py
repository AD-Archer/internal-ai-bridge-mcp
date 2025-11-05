"""Client helper for talking to the in-house AI webhook backend."""

from __future__ import annotations

from typing import Any

import httpx


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
            raise AIWebhookError(f"Webhook call failed: {exc.response.status_code} {body}") from exc

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return {"status_code": response.status_code, "body": response.text}

    async def start_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Trigger a new AI message via webhook."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.base_url, json=payload, headers=self._build_headers())
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
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method_upper,
                url,
                json=payload,
                headers=self._build_headers(headers, secret),
            )
        return self._handle_response(response)
