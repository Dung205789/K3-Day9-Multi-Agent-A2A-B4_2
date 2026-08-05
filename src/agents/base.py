"""Shared agent machinery: scoped data access, LLM call, numeric guard."""
from __future__ import annotations

import time
from typing import Any

from ..a2a import Bus, Message
from ..config import AGENT_MODELS
from ..datastore import DataStore, ScopedView, scoped
from ..llm import chat_json


class Agent:
    """Base class. Subclasses implement `handle()`.

    An agent owns three things: a name, a data scope, and a model. It never
    reaches outside its scope - `ScopedView` raises PermissionError if it tries,
    which is how we prove the handoffs are real and not decoration.
    """

    name: str = "agent"
    role: str = ""

    def __init__(self, store: DataStore, bus: Bus):
        self.store = store
        self.bus = bus
        self.view: ScopedView = scoped(store, self.name)
        self.model = AGENT_MODELS.get(self.name, AGENT_MODELS["coordinator"])
        self.divergences: list[dict] = []

    # -- LLM -----------------------------------------------------------
    def think(self, system: str, user: str, schema_hint: str = "", max_tokens: int = 700):
        data, meta = chat_json(
            self.model, system, user, schema_hint=schema_hint, max_tokens=max_tokens
        )
        return data, meta

    # -- numeric guard --------------------------------------------------
    def reconcile(
        self,
        field: str,
        llm_value: Any,
        truth: Any,
        tol: float = 0.005,
        severity: str = "critical",
    ) -> Any:
        """Trust the data, not the model - but record every disagreement.

        LLMs are good at reading a rule and bad at adding decimals. We let the
        model produce the figure anyway so we can measure how often it drifts,
        then hand the deterministic value downstream.

        `severity` separates "the model would have picked the wrong policy
        branch" (critical) from cosmetic drift like rounding 9.62 days to 9
        (minor). Only critical drift costs confidence.
        """
        ok = True
        if isinstance(truth, (int, float)) and not isinstance(truth, bool):
            try:
                ok = abs(float(llm_value) - float(truth)) <= tol
            except (TypeError, ValueError):
                ok = False
        elif isinstance(truth, bool):
            ok = bool(llm_value) is truth
        elif isinstance(truth, list):
            # Order carries no meaning for ID sets - only membership does.
            try:
                ok = set(map(str, llm_value or [])) == set(map(str, truth))
            except TypeError:
                ok = False
        else:
            ok = (llm_value if llm_value is not None else None) == truth
        if not ok:
            self.divergences.append(
                {
                    "agent": self.name,
                    "field": field,
                    "llm": llm_value,
                    "data": truth,
                    "severity": severity,
                }
            )
        return truth

    # -- messaging ------------------------------------------------------
    def inform(self, recipient: str, intent: str, payload: dict, **meta) -> Message:
        return self.bus.send(self.name, recipient, "inform", intent, payload, **meta)

    def handle(self, message: Message) -> Message:  # pragma: no cover - interface
        raise NotImplementedError


def timed(fn):
    """Decorator that stamps wall-clock duration onto the returned message."""

    def wrapper(self, message, *a, **kw):
        started = time.perf_counter()
        result = fn(self, message, *a, **kw)
        if isinstance(result, Message):
            result.meta["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return result

    return wrapper


JSON_ONLY = "Chỉ trả về một JSON object hợp lệ, không markdown, không giải thích ngoài JSON."
