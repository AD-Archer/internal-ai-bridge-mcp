"""CLI entry point for the MCP bridge."""

from __future__ import annotations

import asyncio
from typing import Optional

import typer

from .ai_client import AIWebhookError
from .config import SettingsError, load_settings
from .server import run_stdio, run_websocket

app = typer.Typer(help="Run the external-ai MCP bridge service.")


@app.command()
def stdio(env_file: Optional[str] = typer.Option(None, help="Optional .env file to load.")) -> None:
    """Run the MCP server over stdio."""
    try:
        settings = load_settings(env_file=env_file)
    except SettingsError as exc:
        typer.secho(f"Configuration error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc

    try:
        asyncio.run(run_stdio(settings))
    except AIWebhookError as exc:
        typer.secho(f"AI webhook error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(2) from exc
    except KeyboardInterrupt:
        typer.secho("Shutting down (stdio).", fg=typer.colors.YELLOW)


@app.command()
def websocket(
    env_file: Optional[str] = typer.Option(None, help="Optional .env file to load."),
    host: str = typer.Option("0.0.0.0", help="Websocket bind host."),
    port: int = typer.Option(8765, help="Websocket port."),
) -> None:
    """Run the MCP server over WebSocket."""
    try:
        settings = load_settings(env_file=env_file)
    except SettingsError as exc:
        typer.secho(f"Configuration error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc

    try:
        asyncio.run(run_websocket(settings, host=host, port=port))
    except AIWebhookError as exc:
        typer.secho(f"AI webhook error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(2) from exc
    except KeyboardInterrupt:
        typer.secho("Shutting down (websocket).", fg=typer.colors.YELLOW)


def main() -> None:
    """Entrypoint for the `external-ai-mcp` console script."""
    app()


if __name__ == "__main__":
    main()
