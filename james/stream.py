"""
JAMES Streaming Event Bus — Real-time execution telemetry.

Provides a pub/sub event bus for streaming DAG execution events
(node started, completed, failed, etc.) to the CLI or Web UI via Server-Sent Events (SSE).
"""

import json
import queue
import threading
import time
from typing import Any, Callable


class EventBus:
    """
    A thread-safe pub/sub event bus.
    Subscribers receive events as JSON-serializable dictionaries.
    """

    def __init__(self):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        """Subscribe to the event bus. Returns a queue."""
        q = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        """Remove a subscriber queue."""
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def emit(self, event_type: str, data: Any = None) -> None:
        """
        Emit an event to all subscribers.
        Non-blocking: if a subscriber's queue is full, the event is dropped for them.
        """
        event = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        }
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass  # Drop event if subscriber is too slow


class SSEStreamer:
    """Helper for converting EventBus queues into Server-Sent Events (SSE)."""

    @staticmethod
    def generate(bus: EventBus):
        """Generator function that yields SSE formatted strings."""
        q = bus.subscribe()
        try:
            while True:
                # Block until an event is available
                event = q.get()
                # Server-Sent Events format: `data: {"type": "...", ...}\n\n`
                yield f"data: {json.dumps(event)}\n\n"
        except GeneratorExit:
            # Client disconnected
            bus.unsubscribe(q)
        except Exception:
            bus.unsubscribe(q)
