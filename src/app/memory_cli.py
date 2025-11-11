"""CLI entrypoint dedicated to the memory MCP server."""

from __future__ import annotations

import asyncio
from typing import Optional

import typer

from .config import SettingsError, load_settings
from .memory_api import run_memory_stdio

app = typer.Typer(help="Run the conversation-memory MCP server (stdio).")


@app.command()
def stdio(env_file: Optional[str] = typer.Option(None, help="Optional .env file to load.")) -> None:
    """Run the memory MCP server over stdio."""
    try:
        settings = load_settings(env_file=env_file)
    except SettingsError as exc:
        typer.secho(f"Configuration error: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1) from exc

    try:
        asyncio.run(run_memory_stdio(settings))
    except KeyboardInterrupt:
        typer.secho("Shutting down (memory stdio).", fg=typer.colors.YELLOW)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
