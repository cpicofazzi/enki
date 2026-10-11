"""
src/web/routes/stream.py
Server-Sent Events (SSE) streaming endpoint for live logs & run events (F37).
Streams events in real time from EventBus and replays historical events upon connection.
"""

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator
from fastapi import APIRouter, Request, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.engine.events import get_event_bus, RunEvent
from src.engine.run_manager import RunManager
from src.web.security import redact_data

router = APIRouter(prefix="/api/runs", tags=["stream"])


@router.get("/{run_id}/stream")
async def stream_run_events(run_id: str, request: Request):
    """
    SSE stream yielding JSON events for the specified run:
    1. Replays all existing events for late joiners / page refreshes.
    2. Subscribes in-memory to EventBus to push live events as they occur.
    3. Handles client disconnects cleanly.
    """
    event_bus = get_event_bus()
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    # Callback invoked by EventBus from any thread
    def on_event(event: RunEvent):
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception:
            pass

    # Subscribe to EventBus
    event_bus.subscribe(run_id, on_event)

    async def event_generator() -> AsyncGenerator[dict, None]:
        try:
            # 1. Replay historical events
            past_events = event_bus.get_events(run_id)
            for ev in past_events:
                redacted = redact_data(ev.model_dump())
                yield {
                    "event": ev.event_type.value,
                    "data": json.dumps(redacted),
                    "id": ev.event_id
                }

            # 2. Stream live events
            while True:
                # Under some ASGI test clients, is_disconnected can block indefinitely if not awaited with timeout
                try:
                    is_disc = await asyncio.wait_for(request.is_disconnected(), timeout=0.01)
                    if is_disc:
                        break
                except (asyncio.TimeoutError, Exception):
                    pass

                try:
                    ev: RunEvent = await asyncio.wait_for(queue.get(), timeout=1.0)
                    redacted = redact_data(ev.model_dump())
                    yield {
                        "event": ev.event_type.value,
                        "data": json.dumps(redacted),
                        "id": ev.event_id
                    }
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat comment
                    yield {
                        "event": "ping",
                        "data": "{}"
                    }
        finally:
            event_bus.unsubscribe(run_id, on_event)

    return EventSourceResponse(event_generator())
