"""A2A (agent-to-agent) messaging: envelope, bus, and trace recorder.

Every cross-agent interaction goes through `Bus.send()`. Nothing is passed by
side-channel, so `trace.jsonl` is a complete recording of the conversation -
replayable, and what the live UI renders.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# FIPA-style performatives - enough vocabulary to make a handoff explicit.
PERFORMATIVES = (
    "request",      # coordinator -> worker: please investigate
    "inform",       # worker -> coordinator: here are my findings
    "handoff",      # coordinator -> agent: you own the case now, with context
    "query",        # agent -> agent: I need a fact outside my scope
    "confirm",      # verifier -> coordinator: checks passed
    "reject",       # verifier -> coordinator: checks failed, here is why
    "escalate",     # any -> coordinator: I cannot decide
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Message:
    case_id: str
    sender: str
    recipient: str
    performative: str
    intent: str
    payload: dict[str, Any] = field(default_factory=dict)
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    reply_to: str | None = None
    ts: str = field(default_factory=_now)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Bus:
    """Per-case message bus. Thread-safe; supports live subscribers."""

    def __init__(self, case_id: str, recorder: "TraceRecorder | None" = None):
        self.case_id = case_id
        self.messages: list[Message] = []
        self.recorder = recorder
        self._subscribers: list[Callable[[Message], None]] = []
        self._lock = threading.Lock()
        self.t0 = time.perf_counter()

    def subscribe(self, fn: Callable[[Message], None]) -> None:
        self._subscribers.append(fn)

    def send(
        self,
        sender: str,
        recipient: str,
        performative: str,
        intent: str,
        payload: dict | None = None,
        reply_to: str | None = None,
        **meta: Any,
    ) -> Message:
        if performative not in PERFORMATIVES:
            raise ValueError(f"unknown performative: {performative}")
        msg = Message(
            case_id=self.case_id,
            sender=sender,
            recipient=recipient,
            performative=performative,
            intent=intent,
            payload=payload or {},
            reply_to=reply_to,
            meta={"elapsed_ms": round((time.perf_counter() - self.t0) * 1000, 1), **meta},
        )
        with self._lock:
            self.messages.append(msg)
            if self.recorder:
                self.recorder.write(msg)
        for fn in list(self._subscribers):
            try:
                fn(msg)
            except Exception:  # a broken UI subscriber must not kill the run
                pass
        return msg

    def transcript(self) -> list[dict]:
        return [m.to_dict() for m in self.messages]

    def by_sender(self, sender: str) -> list[Message]:
        return [m for m in self.messages if m.sender == sender]

    def last_from(self, sender: str) -> Message | None:
        msgs = self.by_sender(sender)
        return msgs[-1] if msgs else None


class TraceRecorder:
    """Writes trace.jsonl. Truncates on open - the spec wants the latest run only."""

    def __init__(self, *paths: Path, truncate: bool = True):
        self.paths = [Path(p) for p in paths]
        self._lock = threading.Lock()
        self._handles = []
        for p in self.paths:
            p.parent.mkdir(parents=True, exist_ok=True)
            self._handles.append(open(p, "w" if truncate else "a", encoding="utf-8"))

    def write(self, msg: Message) -> None:
        line = json.dumps(msg.to_dict(), ensure_ascii=False)
        with self._lock:
            for h in self._handles:
                h.write(line + "\n")
                h.flush()

    def write_raw(self, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            for h in self._handles:
                h.write(line + "\n")
                h.flush()

    def close(self) -> None:
        with self._lock:
            for h in self._handles:
                h.close()
            self._handles = []

    def __enter__(self) -> "TraceRecorder":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
