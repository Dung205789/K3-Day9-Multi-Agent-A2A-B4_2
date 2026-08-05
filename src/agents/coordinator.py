"""Coordinator Agent.

Owns the per-case pipeline: fan out to the three domain worker agents,
hand off their structured findings to the Policy Agent, then hand the
Policy Agent's proposal to the Verifier Agent for the final, authoritative
output. Every step's input/output is recorded so main.py can emit one
trace.jsonl line per case documenting the full A2A handoff chain.
"""

from __future__ import annotations

import time
from typing import Any

from agents import delivery_agent, order_seller_agent, payment_agent, policy_agent, verifier_agent
from schemas import FinalOutput


def run_case(case: dict) -> tuple[FinalOutput, dict[str, Any]]:
    case_id = case["case_id"]
    order_id = case["customer_request"]["claimed_order_id"]
    message = case["customer_request"]["message"]

    steps: list[dict[str, Any]] = []

    t0 = time.monotonic()
    os_findings = order_seller_agent.analyze(order_id)
    steps.append(
        {
            "agent": "order_seller_agent",
            "elapsed_s": round(time.monotonic() - t0, 3),
            "output": os_findings.model_dump(),
        }
    )

    t0 = time.monotonic()
    delivery_findings = delivery_agent.analyze(order_id)
    steps.append(
        {
            "agent": "delivery_agent",
            "elapsed_s": round(time.monotonic() - t0, 3),
            "output": delivery_findings.model_dump(),
        }
    )

    t0 = time.monotonic()
    payment_findings = payment_agent.analyze(order_id)
    steps.append(
        {
            "agent": "payment_agent",
            "elapsed_s": round(time.monotonic() - t0, 3),
            "output": payment_findings.model_dump(),
        }
    )

    t0 = time.monotonic()
    draft = policy_agent.decide(os_findings, delivery_findings, payment_findings, message)
    steps.append(
        {
            "agent": "policy_agent",
            "elapsed_s": round(time.monotonic() - t0, 3),
            "output": draft.model_dump(),
        }
    )

    t0 = time.monotonic()
    output, verification = verifier_agent.verify(case_id, order_id, draft)
    steps.append(
        {
            "agent": "verifier_agent",
            "elapsed_s": round(time.monotonic() - t0, 3),
            "output": verification,
        }
    )

    trace = {
        "case_id": case_id,
        "order_id": order_id,
        "steps": steps,
    }
    return output, trace
