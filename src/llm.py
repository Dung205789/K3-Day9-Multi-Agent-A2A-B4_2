"""Thin OpenAI wrapper: JSON-mode calls, retries, and token/cost accounting."""
from __future__ import annotations

import json
import re
import threading
import time

from openai import OpenAI

from .config import (
    BASE_URL,
    EXTRA_BODY,
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
            # base_url covers every OpenAI-compatible provider (Groq, Together,
            # OpenRouter, DeepInfra, a local Ollama) - see config.MODEL_SMALL.
            _client = OpenAI(
                api_key=api_key(), timeout=REQUEST_TIMEOUT, base_url=BASE_URL
            )
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


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def extract_object(raw: str) -> dict:
    """Coerce a model reply into a JSON object, or raise ValueError.

    Open-weight models are looser than OpenAI about `response_format`. Qwen3 in
    particular may wrap the answer in a <think> block, or return a JSON *string*
    rather than an object - `json.loads` then hands back a `str` and every
    caller downstream breaks on `.get`. Normalising here keeps that mess out of
    the agents.
    """
    text = _THINK.sub("", raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]

    for candidate in (text, (_OBJECT.search(text) or [None]) and _OBJECT.search(text)):
        if candidate is None:
            continue
        chunk = candidate if isinstance(candidate, str) else candidate.group(0)
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
        # A model that answered with a quoted JSON blob: unwrap once.
        if isinstance(data, str):
            try:
                inner = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(inner, dict):
                return inner
    raise ValueError(f"không lấy được JSON object từ: {text[:200]!r}")


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
                **({"extra_body": EXTRA_BODY} if EXTRA_BODY else {}),
            )
            raw = resp.choices[0].message.content or "{}"
            data = extract_object(raw)
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
        except (json.JSONDecodeError, ValueError) as exc:
            last_err = exc
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": "Trả lời sai định dạng. Trả lại đúng MỘT JSON object "
                           "hợp lệ, bắt đầu bằng { và kết thúc bằng }, không kèm "
                           "giải thích, không dùng khối markdown.",
            })
        except Exception as exc:  # network / rate limit / server error
            last_err = exc
            time.sleep(min(2 ** attempt * 0.5, 8))
    raise LLMError(f"LLM call failed after {MAX_RETRIES} attempts: {last_err}")
