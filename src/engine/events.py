"""
src/engine/events.py
Typed in-memory pub/sub EventBus with thread-safety and append-only event logging.
"""

import threading
import json
from pathlib import Path
from typing import Dict, List, Callable, Optional, Any
from src.engine.models import RunEvent, EventType


class EventBus:
    def __init__(self, runs_base_dir: Optional[Path] = None):
        self._lock = threading.RLock()
        self._listeners: Dict[str, List[Callable[[RunEvent], None]]] = {}
        self._global_listeners: List[Callable[[RunEvent], None]] = []
        self._runs_base_dir = runs_base_dir

    def set_runs_base_dir(self, base_dir: Path) -> None:
        with self._lock:
            self._runs_base_dir = base_dir

    def subscribe(self, run_id: str, callback: Callable[[RunEvent], None]) -> None:
        with self._lock:
            if run_id not in self._listeners:
                self._listeners[run_id] = []
            if callback not in self._listeners[run_id]:
                self._listeners[run_id].append(callback)

    def subscribe_all(self, callback: Callable[[RunEvent], None]) -> None:
        with self._lock:
            if callback not in self._global_listeners:
                self._global_listeners.append(callback)

    def unsubscribe(self, run_id: str, callback: Callable[[RunEvent], None]) -> None:
        with self._lock:
            if run_id in self._listeners and callback in self._listeners[run_id]:
                self._listeners[run_id].remove(callback)
            if callback in self._global_listeners:
                self._global_listeners.remove(callback)

    def clear(self, run_id: Optional[str] = None) -> None:
        with self._lock:
            if run_id:
                self._listeners.pop(run_id, None)
            else:
                self._listeners.clear()
                self._global_listeners.clear()

    def publish(self, event: RunEvent) -> None:
        # 1. Thread-safe copy of listeners
        with self._lock:
            run_callbacks = list(self._listeners.get(event.run_id, []))
            global_callbacks = list(self._global_listeners)
            runs_dir = self._runs_base_dir

        # 2. Append to data/runs/<run_id>/events.jsonl (skip for deleted runs)
        if runs_dir and event.run_id and event.event_type != EventType.RUN_DELETED:
            try:
                run_dir = runs_dir / event.run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                events_file = run_dir / "events.jsonl"
                with open(events_file, "a", encoding="utf-8") as f:
                    f.write(event.model_dump_json() + "\n")
            except Exception:
                # Event logging to disk should never crash in-memory execution
                pass

        # 3. Dispatch to listeners with error isolation
        for cb in run_callbacks:
            try:
                cb(event)
            except Exception:
                pass

        for cb in global_callbacks:
            try:
                cb(event)
            except Exception:
                pass

    def get_events(self, run_id: str) -> List[RunEvent]:
        """Reads persisted events from events.jsonl for replay or late subscribers."""
        if not self._runs_base_dir:
            return []
        events_file = self._runs_base_dir / run_id / "events.jsonl"
        if not events_file.is_file():
            return []
        events = []
        with open(events_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(RunEvent.model_validate_json(line))
                    except Exception:
                        pass
        return events


# Singleton instance for shared access across engine and presentation layers
_GLOBAL_EVENT_BUS: Optional[EventBus] = None

def get_event_bus() -> EventBus:
    global _GLOBAL_EVENT_BUS
    if _GLOBAL_EVENT_BUS is None:
        _GLOBAL_EVENT_BUS = EventBus()
    return _GLOBAL_EVENT_BUS
