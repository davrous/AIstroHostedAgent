"""Preserve trusted proxy metadata while the Foundry adapter streams a response."""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from collections.abc import AsyncIterable
from typing import Any

from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.responses import ResponseContext
from azure.ai.agentserver.responses.models import CreateResponse, ResponseStreamEvent

from astronomy_tool import RenderContext, render_context


class AstronomyResponsesHost(ResponsesHostServer):
    async def _handle_response(
        self,
        request: CreateResponse,
        context: ResponseContext,
        cancellation_signal: asyncio.Event,
    ) -> AsyncIterable[ResponseStreamEvent | dict[str, Any]]:
        scope = (request.metadata or {}).get("aistro_scope")
        if scope is not None and not re.fullmatch(r"[a-f0-9]{64}", scope):
            raise ValueError("Invalid astronomical conversation scope.")
        if scope is None:
            owner = context.conversation_id or uuid.uuid4().hex
            scope = hashlib.sha256(f"inspector:{owner}".encode()).hexdigest()
        stream = await super()._handle_response(request, context, cancellation_signal)

        async def scoped_stream():
            token = render_context.set(RenderContext(scope))
            try:
                async for event in stream:
                    yield event
            finally:
                render_context.reset(token)

        return scoped_stream()
