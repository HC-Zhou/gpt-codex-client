from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from ._errors import StreamError
from ._types import JsonObject, Response


class CancelHandle(Protocol):
    def cancel(self) -> None: ...


@dataclass(eq=False)
class Entry:
    session_id: str | None
    endpoint: str
    created_at: float
    last_used: float
    busy: bool = True
    valid: bool = True
    socket: Any = None
    timer: CancelHandle | None = None
    generation: int = 0
    body: JsonObject | None = None
    response_id: str | None = None
    output: list[JsonObject] | None = None


def canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    )


def plan_request(entry: Entry, body: JsonObject) -> JsonObject:
    full = deepcopy(body)
    if body.get("previous_response_id") is not None or not entry.body or not entry.response_id:
        return full
    old = {k: v for k, v in entry.body.items() if k not in {"input", "previous_response_id"}}
    new = {k: v for k, v in body.items() if k not in {"input", "previous_response_id"}}
    baseline = [*entry.body.get("input", []), *(entry.output or [])]
    current = body.get("input", [])
    if canonical(old) == canonical(new) and canonical(current[: len(baseline)]) == canonical(
        baseline
    ):
        full["previous_response_id"] = entry.response_id
        full["input"] = deepcopy(current[len(baseline) :])
    else:
        entry.body = entry.response_id = entry.output = None
    return full


class SessionPool:
    """I/O-free registry. Mutations hold a short lock; disposal occurs outside it."""

    def __init__(self, max_size: int = 32, idle_timeout: float = 300.0) -> None:
        if type(max_size) is not int or max_size < 0:
            raise ValueError("session_cache_max_size must be a non-negative integer")
        if isinstance(idle_timeout, bool) or not math.isfinite(idle_timeout) or idle_timeout <= 0:
            raise ValueError("session_cache_idle_timeout must be finite and positive")
        self.max_size = max_size
        self.idle_timeout = idle_timeout
        self.clock: Callable[[], float] = time.monotonic
        self.lock = threading.Lock()
        self.entries: dict[str, Entry] = {}
        self.active: set[Entry] = set()
        self.closed = False

    def _remove(self, entry: Entry) -> None:
        entry.valid = False
        entry.generation += 1
        if entry.timer:
            entry.timer.cancel()
            entry.timer = None
        if entry.session_id is not None and self.entries.get(entry.session_id) is entry:
            del self.entries[entry.session_id]
        self.active.discard(entry)
        entry.body = entry.response_id = entry.output = None

    def reserve(
        self, session_id: str | None, endpoint: str, *, manual: bool = False
    ) -> tuple[Entry, list[Entry]]:
        garbage: list[Entry] = []
        with self.lock:
            if self.closed:
                raise StreamError("Client is closed")
            now = self.clock()
            for entry in list(self.active):
                if entry.endpoint != endpoint or (
                    not entry.busy
                    and (
                        now - entry.last_used >= self.idle_timeout
                        or now - entry.created_at >= 55 * 60
                    )
                ):
                    self._remove(entry)
                    garbage.append(entry)
            cached = self.entries.get(session_id) if session_id is not None else None
            if cached is not None and not cached.busy and not manual:
                cached.busy = True
                cached.generation += 1
                if cached.timer:
                    cached.timer.cancel()
                    cached.timer = None
                return cached, garbage
            entry = Entry(session_id, endpoint, now, now)
            persist = session_id is not None and not manual and cached is None and self.max_size > 0
            if persist and len(self.entries) >= self.max_size:
                idle = [e for e in self.entries.values() if not e.busy]
                if idle:
                    evicted = min(idle, key=lambda e: e.last_used)
                    self._remove(evicted)
                    garbage.append(evicted)
                else:
                    persist = False
            if persist and session_id is not None:
                self.entries[session_id] = entry
            self.active.add(entry)
            return entry, garbage

    def attach(self, entry: Entry, socket: Any) -> bool:
        with self.lock:
            if not entry.valid:
                return False
            entry.socket = socket
            return True

    def release(self, entry: Entry, body: JsonObject, response: Response | None) -> bool:
        """Return true only when the connection should be retained."""
        with self.lock:
            keep = (
                entry.valid
                and entry.session_id is not None
                and self.entries.get(entry.session_id) is entry
                and response is not None
                and response.status == "completed"
                and bool(response.id)
                and body.get("previous_response_id") is None
            )
            if not keep:
                self._remove(entry)
                return False
            assert response is not None
            entry.body = deepcopy(body)
            entry.output = deepcopy(response.output)
            entry.response_id = response.id
            entry.busy = False
            entry.last_used = self.clock()
            return True

    def schedule(
        self,
        entry: Entry,
        schedule: Callable[[float, Callable[[], None]], CancelHandle],
        dispose: Callable[[Entry], None],
    ) -> None:
        with self.lock:
            if not entry.valid or entry.busy:
                return
            generation = entry.generation

            def expire() -> None:
                with self.lock:
                    if not entry.valid or entry.busy or entry.generation != generation:
                        return
                    self._remove(entry)
                dispose(entry)

            entry.timer = schedule(self.idle_timeout, expire)

    def clear(self, session_id: str | None = None, *, close: bool = False) -> list[Entry]:
        with self.lock:
            if close:
                self.closed = True
            removed = [e for e in self.active if session_id is None or e.session_id == session_id]
            for entry in removed:
                self._remove(entry)
            return removed
