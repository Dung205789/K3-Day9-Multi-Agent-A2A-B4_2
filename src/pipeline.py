"""End-to-end orchestration for a single case.

Flow (every arrow is a recorded A2A message):

    customer -> coordinator            open_case
    coordinator -> {order_seller, payment, delivery}   request/investigate   (parallel)
    {…} -> coordinator                 inform/findings
    coordinator -> policy              handoff/apply_policy
    policy -> coordinator              inform/policy_verdict
    coordinator -> verifier            handoff/verify_draft
    verifier -> coordinator            confirm|reject/verification_report
    coordinator -> case_file           inform/final_summary
"""
from __future__ import annotations

import time
from typing import Callable

from .a2a import Bus, Message, TraceRecorder
from .agents.coordinator import CoordinatorAgent, cap
from .config import MAX_ACTIONS, MAX_EVIDENCE, POLICY_VERSION
from .datastore import DataStore, money
from .llm import USAGE
from .policy import build_evidence, evaluate


def facts_from_bundle(bundle: dict) -> dict:
    """Rebuild a fact sheet purely from what the agents reported.

    The coordinator has no data scope, so this is the only view of the order it
    is allowed to have - assembled from A2A payloads, not from the CSVs.
    """
    os_, pay, dlv = bundle["order_seller"], bundle["payment"], bundle["delivery"]
    tl = dlv.get("timeline", {})
    return {
        "found": True,
        "order_id": os_["order_id"],
        "order_status": os_["order_status"],
        "item_ids": os_["item_ids"],
        "seller_ids": os_["seller_ids"],
        "late_seller_ids": os_["late_handoff_seller_ids"],
        "payment_ids": pay["payment_ids"],
        "item_count": os_["item_count"],
        "payment_count": pay["payment_count"],
        "item_total_brl": os_["item_total_brl"],
        "freight_total_brl": os_["freight_total_brl"],
        "payment_total_brl": pay["payment_total_brl"],
        "expected_total_brl": pay["expected_total_brl"],
        "payment_gap_brl": pay["gap_brl"],
        "payment_matches": pay["payment_matches"],
        "delivered_after_estimate": dlv["delivered_after_estimate"],
        "carrier_after_shipping_limit": dlv["carrier_after_shipping_limit"],
        "delivery_delay_days": dlv.get("delay_days"),
        "purchase_ts": tl.get("purchase"),
        "carrier_ts": tl.get("carrier"),
        "delivered_ts": tl.get("delivered"),
        "estimated_ts": tl.get("estimated"),
    }


def empty_output(case_id: str, order_id: str | None) -> dict:
    """Schema-valid shell for an order that does not exist in the dataset."""
    return {
        "case_id": case_id,
        "assessment": {
            "primary_issue": "unsupported_late_claim",
            "case_status": "no_action",
            "confidence": 0.3,
        },
        "affected_entities": {
            "order_ids": [order_id] if order_id else [],
            "item_ids": [], "seller_ids": [], "payment_ids": [],
        },
        "root_cause_analysis": {
            "ranked_causes": [{"cause_code": "DELIVERY_WITHIN_ESTIMATE", "rank": 1}],
            "responsible_parties": [],
        },
        "evidence_ids": ["policy:DELIVERY_WITHIN_ESTIMATE"],
        "financial_resolution": {
            "currency": "BRL", "item_total_brl": 0.0, "freight_total_brl": 0.0,
            "payment_total_brl": 0.0, "recommended_refund_brl": 0.0,
        },
        "resolution_actions": ["reject_late_refund"],
    }


def run_case(
    case: dict,
    store: DataStore,
    recorder: TraceRecorder | None = None,
    on_message: Callable[[Message], None] | None = None,
) -> dict:
    """Run the whole agent team over one case. Returns result + diagnostics."""
    started = time.perf_counter()
    case_id = case["case_id"]
    order_id = case.get("customer_request", {}).get("claimed_order_id")

    bus = Bus(case_id, recorder)
    if on_message:
        bus.subscribe(on_message)

    bus.send(
        "customer", "coordinator", "request", "open_case",
        {
            "case_id": case_id,
            "opened_at": case.get("opened_at"),
            "message": case.get("customer_request", {}).get("message"),
            "claimed_order_id": order_id,
            "policy_version": case.get("policy_version", POLICY_VERSION),
        },
    )

    coord = CoordinatorAgent(store, bus)
    triage = coord.triage(case)
    replies = coord.dispatch(order_id, case_id)

    escalated = [m for m in replies.values() if m.performative == "escalate"]
    if escalated:
        bus.send(
            "coordinator", "case_file", "inform", "final_summary",
            {"customer_summary": "Không tìm thấy đơn hàng trong dữ liệu.",
             "internal_note": escalated[0].payload.get("reason", ""), "confidence": 0.3},
        )
        return {
            "case_id": case_id,
            "output": empty_output(case_id, order_id),
            "transcript": bus.transcript(),
            "triage": triage,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": "order_not_found",
        }

    bundle = {name: msg.payload for name, msg in replies.items()}
    facts = facts_from_bundle(bundle)

    # Deterministic ground truth, computed from the same handed-over facts.
    engine = evaluate(facts)

    # LLM policy verdict (independent path).
    verdict_msg = coord.to_policy(case, bundle)
    verdict = verdict_msg.payload

    agrees = verdict.get("primary_issue") == engine["primary_issue"]
    if not agrees:
        bus.send(
            "coordinator", "policy", "reject", "policy_disagreement",
            {
                "llm_issue": verdict.get("primary_issue"),
                "engine_issue": engine["primary_issue"],
                "resolution": "áp dụng kết luận của rule engine tất định",
                "engine_checks": engine["checks"],
            },
        )

    issue = engine["primary_issue"]
    evidence = build_evidence(facts, engine)
    parties = engine["responsible_parties"]

    draft = {
        "case_id": case_id,
        "assessment": {
            "primary_issue": issue,
            "case_status": engine["case_status"],
            "confidence": 0.9,
        },
        "affected_entities": {
            "order_ids": cap([facts["order_id"]]),
            "item_ids": cap(facts["item_ids"]),
            "seller_ids": cap(facts["seller_ids"]),
            "payment_ids": cap(facts["payment_ids"]),
        },
        "root_cause_analysis": {
            "ranked_causes": [{"cause_code": engine["root_cause_code"], "rank": 1}],
            "responsible_parties": parties,
        },
        "evidence_ids": evidence[:MAX_EVIDENCE],
        "financial_resolution": {
            "currency": "BRL",
            "item_total_brl": money(facts["item_total_brl"]),
            "freight_total_brl": money(facts["freight_total_brl"]),
            "payment_total_brl": money(facts["payment_total_brl"]),
            "recommended_refund_brl": money(engine["recommended_refund_brl"]),
        },
        "resolution_actions": engine["resolution_actions"][:MAX_ACTIONS],
    }

    report_msg = coord.to_verifier(draft, facts, bundle)
    report = report_msg.payload
    final = report["draft"]

    # Confidence: agreement between the two independent policy paths, minus
    # penalties for anything the verifier had to repair.
    llm_review = report.get("llm_review", {})
    confidence = 0.95
    if not agrees:
        confidence -= 0.15
    if not llm_review.get("approved", True):
        confidence -= 0.08
    confidence += float(llm_review.get("confidence_adjustment", 0.0) or 0.0)
    confidence -= 0.02 * min(len(report.get("repairs", [])), 4)
    all_divergences = [
        d for a in (*coord.workers.values(), coord.policy_agent) for d in a.divergences
    ]
    critical = [d for d in all_divergences if d.get("severity") == "critical"]
    # The guard already corrected these, so the answer is right either way -
    # drift only signals that the model was shakier than usual on this case.
    confidence -= 0.02 * min(len(critical), 3)
    confidence = round(max(0.35, min(0.99, confidence)), 2)
    final["assessment"]["confidence"] = confidence

    summary_msg = coord.summarize(
        {
            "case_id": case_id,
            "customer_message": case.get("customer_request", {}).get("message"),
            "engine_conclusion": {
                "primary_issue": engine["primary_issue"],
                "label": engine["label"],
                "reason": engine["reason"],
                "refund_brl": engine["recommended_refund_brl"],
                "responsible_parties": parties,
            },
            "policy_agent_verdict": verdict,
            "agreement": agrees,
            "verifier": {"issues": report["issues"], "repairs": report["repairs"],
                         "llm_review": llm_review},
        }
    )

    return {
        "case_id": case_id,
        "output": final,
        "transcript": bus.transcript(),
        "triage": triage,
        "bundle": bundle,
        "engine": engine,
        "policy_verdict": verdict,
        "verification": {k: v for k, v in report.items() if k != "draft"},
        "summary": summary_msg.payload,
        "agreement": agrees,
        "divergences": all_divergences,
        "critical_divergences": len(critical),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "usage": USAGE.snapshot(),
        "error": None,
    }
