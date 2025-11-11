"""Conversation memory surface exposed as both HTTP routes and an MCP server."""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Mapping

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .config import Settings
from .storage import ConversationMessage, ConversationStore, format_history_for_prompt

logger = logging.getLogger(__name__)

SESSION_KEY_ALIASES = {
    "session_id",
    "sessionid",
    "session",
    "x_session_id",
    "x_session",
    "conversation_id",
    "conversationid",
    "conversation",
    "x_conversation_id",
}

ALLOWED_RESPONSE_STATUSES = {"info", "success", "error", "complete"}


class SessionNotFoundError(RuntimeError):
    """Raised when callers reference a session that does not exist."""


def _serialize_messages(messages: list[ConversationMessage]) -> list[dict[str, Any]]:
    return [
        {
            "role": msg.role,
            "content": msg.content,
            "metadata": msg.metadata,
            "created_at": msg.created_at,
        }
        for msg in messages
    ]


class MemoryService:
    """Shared business logic for conversation history features."""

    def __init__(self, store: ConversationStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    def _normalize_limit(self, limit: int | str | None) -> int:
        default = self.settings.conversation_history_limit
        if limit is None:
            return default
        try:
            parsed = int(limit)
        except (TypeError, ValueError):
            logger.warning("Invalid limit '%s'. Falling back to %s.", limit, default)
            return default
        if parsed <= 0:
            logger.warning("Non-positive limit '%s'. Falling back to %s.", limit, default)
            return default
        return parsed

    def list_sessions(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self.store.list_sessions(limit=limit or 100)

    def _fetch_messages(self, session_id: str, limit: int | None = None) -> list[ConversationMessage]:
        limit_value = self._normalize_limit(limit) if limit is not None else None
        return self.store.get_messages(session_id, limit=limit_value)

    def conversation_detail(self, session_id: str, limit: int | None = None) -> dict[str, Any]:
        messages = self._fetch_messages(session_id, limit=limit)
        if not messages:
            raise SessionNotFoundError(session_id)
        return {"session_id": session_id, "messages": _serialize_messages(messages)}

    def recall_memory(self, session_id: str, limit: int | str | None = None) -> dict[str, Any]:
        limit_value = self._normalize_limit(limit)
        messages = self.store.get_messages(session_id, limit=limit_value)
        serialized = _serialize_messages(messages)
        context_block = format_history_for_prompt(messages) if messages else ""
        user_messages = [msg["content"] for msg in serialized if msg["role"] == "user"]
        assistant_messages = [msg["content"] for msg in serialized if msg["role"] == "assistant"]
        payload = {
            "session_id": session_id,
            "messages": serialized,
            "context_block": context_block,
            "user_messages": user_messages,
            "assistant_messages": assistant_messages,
            "message_count": len(serialized),
            "limit_applied": limit_value,
        }
        return payload

    def delete_session(self, session_id: str) -> None:
        self.store.delete_session(session_id)

    def record_ai_response(
        self,
        *,
        session_id: str | None = None,
        message: str | None = None,
        payload: Mapping[str, Any] | None = None,
        role: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Persist an AI response (or any role) into the conversation history."""
        if payload is not None and not isinstance(payload, Mapping):
            raise ValueError("payload must be a JSON object.")

        payload_dict: dict[str, Any] = dict(payload or {})
        candidate_session = session_id or _extract_session_id(payload_dict)
        if not candidate_session:
            raise ValueError("session_id is required to record a response.")

        resolved_status = status or payload_dict.get("status")
        if resolved_status:
            if resolved_status not in ALLOWED_RESPONSE_STATUSES:
                raise ValueError(
                    f"Invalid status '{resolved_status}'. Expected one of: {sorted(ALLOWED_RESPONSE_STATUSES)}."
                )
            payload_dict.setdefault("status", resolved_status)

        resolved_role = role or payload_dict.get("role") or "assistant"
        resolved_message = message
        message_inferred = False
        if resolved_message is None:
            for key in ("message", "payload_summary", "content"):
                value = payload_dict.get(key)
                if value:
                    resolved_message = str(value)
                    break
        if resolved_message is None:
            resolved_message = json.dumps(payload_dict, ensure_ascii=False)
            message_inferred = True

        payload_dict.setdefault("sessionID", candidate_session)
        payload_dict.setdefault("session_id", candidate_session)
        payload_dict.setdefault("role", resolved_role)
        payload_dict.setdefault("message", resolved_message)

        self.store.record_message(
            candidate_session,
            resolved_role,
            resolved_message,
            metadata=payload_dict,
        )

        return {
            "session_id": candidate_session,
            "role": resolved_role,
            "message": resolved_message,
            "status": resolved_status,
            "stored": True,
            "message_inferred": message_inferred,
            "payload": payload_dict,
        }


ResponseHook = Callable[[dict[str, Any]], Awaitable[None]]


def register_memory_mcp_surface(
    mcp: FastMCP,
    store: ConversationStore,
    settings: Settings,
    *,
    response_handler: ResponseHook | None = None,
) -> None:
    """Attach memory tools/resources to an existing MCP server."""
    service = MemoryService(store, settings)

    async def _dispatch_response(record: dict[str, Any]) -> None:
        if response_handler is None:
            return
        try:
            await response_handler(record)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Response handler failed: %s", exc)

    @mcp.resource("memory://sessions")
    def sessions_resource() -> str:
        return json.dumps({"sessions": service.list_sessions()}, indent=2)

    @mcp.resource("memory://health")
    def health_resource() -> str:
        status = {"status": "ok", "conversation_limit": settings.conversation_history_limit}
        return json.dumps(status, indent=2)

    @mcp.tool()
    async def list_conversations(limit: int | None = None) -> dict[str, Any]:
        """Return the most recently updated sessions stored in the memory DB."""
        return {"sessions": service.list_sessions(limit=limit or 100)}

    @mcp.tool()
    async def get_conversation(session_id: str, limit: int | None = None) -> dict[str, Any]:
        """Dump role/content/metadata for a session."""
        try:
            return service.conversation_detail(session_id, limit=limit)
        except SessionNotFoundError as exc:  # pragma: no cover - surfaced to MCP clients
            raise ValueError(f"Session '{session_id}' not found.") from exc

    @mcp.tool()
    async def recall_conversation_context(session_id: str, limit: int | None = None) -> dict[str, Any]:
        """
        Return a context block plus separated user/assistant turns for a session.
        """
        return service.recall_memory(session_id, limit=limit)

    @mcp.tool()
    async def delete_conversation(session_id: str) -> dict[str, Any]:
        """Remove a stored session and all of its messages."""
        service.delete_session(session_id)
        return {"status": "deleted", "session_id": session_id}

    @mcp.tool()
    async def send_user_response(
        *,
        session_id: str | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
        role: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """
        Send a user response into the conversation memory.

        Provide either a session_id argument or embed it within the payload as any of
        sessionID/session_id/session, etc. If message is omitted the service will
        fall back to payload["message"] or serialize the payload for storage.
        """

        record = service.record_ai_response(
            session_id=session_id,
            message=message,
            payload=payload,
            role=role or "user",
            status=status,
        )
        await _dispatch_response(record)
        return record


def build_memory_server(
    store: ConversationStore,
    settings: Settings,
    *,
    response_handler: ResponseHook | None = None,
) -> FastMCP:
    """Create a standalone MCP server dedicated to memory operations."""
    mcp = FastMCP(
        name="conversation-memory",
        instructions=(
            "This server exposes conversation transcripts persisted by the external AI bridge. "
            "Use the available tools to list sessions, fetch message history, recall a ready-to-use "
            "context block, or delete transcripts when they are no longer needed."
        ),
        website_url="https://modelcontextprotocol.io",
    )
    register_memory_mcp_surface(mcp, store, settings, response_handler=response_handler)
    return mcp


async def run_memory_stdio(settings: Settings) -> None:
    """Run the conversation memory MCP server over stdio."""
    store = ConversationStore(settings.conversation_db_path)
    server = build_memory_server(store, settings)
    await server.run_stdio_async()


def _extract_session_id(source: Any) -> str | None:
    if not source or not hasattr(source, "items"):
        return None

    items = source.items()
    for key, value in items:
        if value is None:
            continue
        key_str = str(key).lower().replace("-", "_")
        if key_str in SESSION_KEY_ALIASES:
            candidate = _coerce_session_value(value)
            if candidate:
                return candidate
        nested = _extract_from_value(value)
        if nested:
            return nested
    return None


def _extract_from_value(value: Any) -> str | None:
    if isinstance(value, (list, tuple)):
        for item in value:
            nested = _extract_from_value(item)
            if nested:
                return nested
        return None
    if isinstance(value, Mapping) or hasattr(value, "items"):
        return _extract_session_id(value)
    return None


def _coerce_session_value(value: Any) -> str | None:
    if isinstance(value, (list, tuple)):
        for item in value:
            result = _coerce_session_value(item)
            if result:
                return result
        return None
    if isinstance(value, Mapping) or hasattr(value, "items"):
        return _extract_session_id(value)
    if value is None:
        return None
    return str(value)


def build_memory_routes(store: ConversationStore, settings: Settings) -> list[Route]:
    """Create Starlette routes that expose conversation history helpers."""
    service = MemoryService(store, settings)

    async def list_conversations(request: Request) -> Response:
        try:
            limit = int(request.query_params.get("limit", "100"))
        except ValueError:
            limit = 100
        sessions = service.list_sessions(limit=limit)
        return JSONResponse({"sessions": sessions})

    async def conversation_detail_handler(request: Request) -> Response:
        session_id = request.path_params["session_id"]
        if request.method == "DELETE":
            service.delete_session(session_id)
            return JSONResponse({"status": "deleted", "session_id": session_id})

        try:
            payload = service.conversation_detail(session_id)
        except SessionNotFoundError:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return JSONResponse(payload)

    async def recall_memory_handler(request: Request) -> Response:
        payload: dict[str, Any] = {}
        query_snapshot = dict(request.query_params)
        logger.info("Memory recall request received: method=%s query=%s", request.method, query_snapshot)

        if request.method == "GET":
            params = request.query_params
            session_id = _extract_session_id(params)
            limit_raw = params.get("limit") or params.get("history_limit")
        else:
            try:
                payload = await request.json()
                if not isinstance(payload, dict):
                    logger.warning("Memory recall received non-dict JSON body: %s", payload)
                    payload = {}
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning("Failed to parse recall JSON body: %s", exc)
                payload = {}
            body_session = _extract_session_id(payload)
            session_id = body_session or _extract_session_id(request.query_params) or _extract_session_id(request.headers)
            limit_raw = (
                payload.get("limit")
                or payload.get("history_limit")
                or request.query_params.get("limit")
                or request.query_params.get("history_limit")
            )
        if request.method == "GET":
            session_id = session_id or _extract_session_id(request.headers)

        session_id = session_id or _extract_session_id(payload.get("params")) if payload else session_id

        if not session_id:
            logger.info("Memory recall probe without session id. Returning healthy status.")
            base_url = str(request.base_url).rstrip("/")
            return JSONResponse(
                {
                    "status": "healthy",
                    "requires_session_id": True,
                    "message": "Provide session_id via body (sessionID/conversationID) or query once available.",
                    "x-mcp": {
                        "transport": "stdio|websocket",
                        "endpoint": f"{base_url}/mcp/openai",
                        "notes": "Clients should open an MCP connection and call the memory tools/resources."
                    }
                }
            )

        payload = service.recall_memory(session_id, limit_raw or settings.conversation_history_limit)
        logger.info(
            "Memory recall served session=%s message_count=%s limit=%s",
            session_id,
            payload["message_count"],
            payload["limit_applied"],
        )
        return JSONResponse(payload)

    return [
        Route("/conversations", list_conversations, methods=["GET"]),
        Route("/conversations/{session_id}", conversation_detail_handler, methods=["GET", "DELETE"]),
        Route("/memory/recall", recall_memory_handler, methods=["POST", "GET"]),
    ]
