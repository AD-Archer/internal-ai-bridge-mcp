"""
Ninjacat Pipeline for OpenWeb UI
"""

import os
import asyncio
import httpx
import logging
from typing import List, Union, Optional, Dict, Any, AsyncIterator
from pydantic import BaseModel, Field
from open_webui.env import SRC_LOG_LEVELS


class Pipe:
    """
    Pipeline for interacting with Ninjacat AI backend.
    """

    # Configuration valves for the pipeline
    class Valves(BaseModel):
        AI_WEBHOOK_URL: str = Field(
            default=os.getenv("AI_WEBHOOK_URL", ""),
            description="Webhook URL for the Ninjacat AI backend.",
        )
        AI_API_KEY: Optional[str] = Field(
            default=os.getenv("AI_API_KEY", ""),
            description="API key for the Ninjacat backend (optional).",
        )
        TIMEOUT: float = Field(
            default=float(os.getenv("AI_TIMEOUT", "30.0")),
            description="Timeout for webhook requests in seconds.",
        )

    def __init__(self):
        """Initializes the Pipe instance."""
        self.valves = self.Valves()

        # Setup logging
        self.log = logging.getLogger("ninjacat.pipe")
        self.log.setLevel(SRC_LOG_LEVELS.get("OPENAI", logging.INFO))

    def pipes(self) -> List[Dict[str, str]]:
        """
        Returns a list of available models.

        Returns:
            List of dictionaries containing model id and name.
        """
        return [{"id": "ninjacat", "name": "Ninjacat AI"}]

    async def _call_backend(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call the Ninjacat backend webhook.

        Args:
            payload: The payload to send

        Returns:
            Response from the backend
        """
        headers = {"Content-Type": "application/json"}
        if self.valves.AI_API_KEY:
            headers["Authorization"] = f"Bearer {self.valves.AI_API_KEY}"

        async with httpx.AsyncClient(timeout=self.valves.TIMEOUT) as client:
            response = await client.post(
                self.valves.AI_WEBHOOK_URL,
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            return response.json()

    async def pipe(
        self,
        body: Dict[str, Any],
        __metadata__: dict[str, Any],
        __event_emitter__: callable,
        __tools__: dict[str, Any] | None,
        __request__: Optional[Any] = None,
        __user__: Optional[dict] = None,
    ) -> Union[str, AsyncIterator[str]]:
        """
        Main method for sending requests to the Ninjacat backend.

        Args:
            body: The request body containing messages and other parameters.
            __metadata__: Request metadata
            __event_emitter__: Event emitter for status updates
            __tools__: Available tools
            __request__: FastAPI request object
            __user__: User information

        Returns:
            Response from Ninjacat backend.
        """
        try:
            messages = body.get("messages", [])
            if not messages:
                return "Error: No messages provided"

            # Extract the last user message
            prompt = ""
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    prompt = msg.get("content", "")
                    break

            if not prompt:
                return "Error: No user message found"

            # Prepare payload for backend
            payload = {
                "prompt": prompt,
                "sessionID": str(id(body)),  # Use request id as session
            }

            # Add optional metadata
            if body.get("temperature"):
                payload["temperature"] = body["temperature"]
            if body.get("max_tokens"):
                payload["max_tokens"] = body["max_tokens"]

            self.log.debug(f"Sending payload to backend: {payload}")

            # Call the backend
            response_data = await self._call_backend(payload)

            self.log.debug(f"Received response from backend: {response_data}")

            # Extract the message
            content = response_data.get("message", "No response from backend")

            # Check for streaming
            stream = body.get("stream", False)
            if stream:
                # Simple streaming - yield the content as a single chunk
                import json
                chunk = {
                    "choices": [
                        {
                            "delta": {"content": content},
                            "finish_reason": "stop"
                        }
                    ]
                }
                async def generate():
                    yield f"data: {json.dumps(chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                
                return generate()
            else:
                return content

        except httpx.HTTPStatusError as e:
            error_msg = f"Backend error: {e.response.status_code} - {e.response.text}"
            self.log.error(error_msg)
            return error_msg
        except Exception as e:
            error_msg = f"Error calling Ninjacat backend: {e}"
            self.log.exception(error_msg)
            return error_msg