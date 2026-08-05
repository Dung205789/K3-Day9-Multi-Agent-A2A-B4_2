"""Thin OpenAI wrapper: JSON-mode calls, retries, and token/cost accounting."""
from __future__ import annotations

import json
import threading
import time

from openai import OpenAI

from .config import (
    MAX_RETRIES,
    PRICE_IN_PER_M,
    PRICE_OUT_PER_M,
    REQUEST_TIMEOUT,
    TEMPERATURE,
    api_key,
)

_client: OpenAI | None = None
_client_lock = threading.Lock()


def client() -> OpenAI:
    global _client
    with _client_lock:
        if _client is None:
            _client = OpenAI(api_key=api_key(), timeout=REQUEST_TIMEOUT)
    return _client


class Usage:
    """Process-wide token counter so the UI can show a real cost figure."""

    def __init__(self) -> None:
        self.prompt = 0
        self.completion = 0
        self.calls = 0
        self._lock = threading.Lock()

    def add(self, prompt: int, completion: int) -> None:
        with self._lock:
            self.prompt += prompt
            self.completion += completion
            self.calls += 1

    def snapshot(self) -> dict:
        cost = (
            self.prompt / 1_000_000 * PRICE_IN_PER_M
            + self.completion / 1_000_000 * PRICE_OUT_PER_M
        )
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt,
            "completion_tokens": self.completion,
            "total_tokens": self.prompt + self.completion,
            "estimated_cost_usd": round(cost, 4),
        }

    def reset(self) -> None:
        with self._lock:
            self.prompt = self.completion = self.calls = 0


USAGE = Usage()


class LLMError(RuntimeError):
    pass


def chat_json(
    model: str,
    system: str,
    user: str,
    *,
    schema_hint: str = "",
    temperature: float = TEMPERATURE,
    max_tokens: int = 900,
) -> tuple[dict, dict]:
    """Call the model in JSON mode. Returns (parsed_json, call_meta).

    Retries on transport errors and on JSON that fails to parse. The Olist
    agents are all classification/extraction tasks, so a strict JSON contract
    plus temperature 0 keeps them reproducible.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user + ("\n\n" + schema_hint if schema_hint else "")},
    ]
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        started = time.perf_counter()
        try:
            resp = client().chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or "{}"
            data = json.loads(raw)
            usage = resp.usage
            if usage:
                USAGE.add(usage.prompt_tokens, usage.completion_tokens)
            meta = {
                "model": model,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0),
                "attempt": attempt,
            }
            return data, meta
        except json.JSONDecodeError as exc:
            last_err = exc
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {"role": "user", "content": "Trả lời sai JSON. Trả lại đúng một JSON object hợp lệ."}
            )
        except Exception as exc:  # network / rate limit / server error
            last_err = exc
            time.sleep(min(2 ** attempt * 0.5, 8))
    raise LLMError(f"LLM call failed after {MAX_RETRIES} attempts: {last_err}")
