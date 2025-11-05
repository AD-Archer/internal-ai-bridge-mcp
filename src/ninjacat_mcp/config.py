"""Configuration helpers for the MCP bridge."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import BaseModel, Field, HttpUrl, ValidationError


class SettingsError(RuntimeError):
    """Raised when configuration values are invalid or missing."""


class WebhookTarget(BaseModel):
    """Represents an outbound webhook that tools can invoke."""

    url: HttpUrl
    method: str = "POST"
    secret: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)


class Settings(BaseModel):
    """Application configuration loaded from environment variables or a dotenv file."""

    ai_webhook_url: HttpUrl
    ai_api_key: str | None = None
    ai_timeout: float = Field(default=30.0, gt=0)
    extra_webhooks: dict[str, WebhookTarget] = Field(default_factory=dict)

    @classmethod
    def _parse_extra_webhooks(cls, raw: str | None) -> dict[str, WebhookTarget]:
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SettingsError("EXTRA_WEBHOOKS must be valid JSON.") from exc
        if not isinstance(data, dict):
            raise SettingsError("EXTRA_WEBHOOKS must decode to a JSON object.")

        parsed: dict[str, WebhookTarget] = {}
        for name, payload in data.items():
            if not isinstance(payload, dict):
                raise SettingsError(f"Webhook '{name}' must be a JSON object.")
            try:
                parsed[name] = WebhookTarget.model_validate(payload)
            except ValidationError as exc:
                raise SettingsError(f"Invalid webhook config for '{name}'.") from exc
        return parsed

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        """Create settings from an environment mapping."""
        values = dict(os.environ if env is None else env)

        webhook_url = values.get("AI_WEBHOOK_URL")
        if not webhook_url:
            raise SettingsError("AI_WEBHOOK_URL is required.")

        timeout_raw = values.get("AI_TIMEOUT", "30")
        try:
            timeout = float(timeout_raw)
        except ValueError as exc:
            raise SettingsError("AI_TIMEOUT must be numeric.") from exc

        extra_webhooks = cls._parse_extra_webhooks(values.get("EXTRA_WEBHOOKS"))

        try:
            return cls(
                ai_webhook_url=webhook_url,
                ai_api_key=values.get("AI_API_KEY"),
                ai_timeout=timeout,
                extra_webhooks=extra_webhooks,
            )
        except ValidationError as exc:
            raise SettingsError("Invalid configuration values.") from exc

    @classmethod
    def from_env_file(cls, path: str | Path) -> "Settings":
        """Create settings by loading a dotenv file."""
        data = {k: v for k, v in dotenv_values(path).items() if v is not None}
        merged = dict(os.environ)
        merged.update(data)
        return cls.from_env(merged)


def load_settings(env_file: str | Path | None = None, **overrides: Any) -> Settings:
    """Convenience wrapper to load settings from env with optional overrides."""
    base = Settings.from_env_file(env_file) if env_file else Settings.from_env()
    if overrides:
        try:
            return base.model_copy(update=overrides)
        except ValidationError as exc:
            raise SettingsError("Invalid override values.") from exc
    return base
