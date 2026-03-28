import pytest
import queue
from james.stream import EventBus, SSEStreamer


def test_event_bus():
    bus = EventBus()
    q = bus.subscribe()
    
    assert len(bus._subscribers) == 1
    
    bus.emit("test_event", {"key": "value"})
    
    # Should be non-blocking
    event = q.get_nowait()
    assert event["type"] == "test_event"
    assert event["data"]["key"] == "value"
    assert "timestamp" in event
    
    bus.unsubscribe(q)
    assert len(bus._subscribers) == 0


def test_sse_streamer():
    import threading
    bus = EventBus()
    generator = SSEStreamer.generate(bus)
    
    # Emit after generator starts
    def emit_later():
        import time
        time.sleep(0.1)
        bus.emit("hello", {"msg": "world"})
        
    threading.Thread(target=emit_later, daemon=True).start()
    
    # Get the next SSE string from the generator (will block until emit_later fires)
    sse_str = next(generator)
    
    assert sse_str.startswith("data: ")
    assert sse_str.endswith("\n\n")
    assert '"type": "hello"' in sse_str
    assert '"msg": "world"' in sse_str
