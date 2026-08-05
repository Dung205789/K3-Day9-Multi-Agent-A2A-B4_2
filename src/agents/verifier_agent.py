"""Verifier Agent.

Deterministic (no LLM) by design: its job is exactly "kiểm tra ID, số tiền
và schema trước khi ghi file" (README section 7) — recomputes the ground
truth via policy_rules against the real CSVs, cross-checks the Policy
Agent's proposal, and is the sole authority on what actually gets written
to output/. On disagreement the deterministic engine always wins; the
mismatch is recorded for the trace so it is auditable, never silently lost.
"""

from __future__ import annotations

import re

import data_access as da
import policy_rules as pr
from schemas import (
    AffectedEntities,
    Assessment,
    FinalOutput,
    FinancialResolution,
    PolicyDecisionDraft,
    RankedCause,
    ResponsibleParty,
    RootCauseAnalysis,
)

_EVIDENCE_RE = re.compile(
    r"^(order:[^:]+|item:[^:]+:\d+|payment:[^:]+:\d+|seller:[^:]+|policy:[A-Z_]+)$"
)


def _evidence_exists(evidence_id: str) -> bool:
    if not _EVIDENCE_RE.match(evidence_id):
        return False
    kind, *rest = evidence_id.split(":")
    if kind == "order":
        return da.order_exists(rest[0])
    if kind == "item":
        order_id, item_id = rest
        return any(str(i["order_item_id"]) == item_id for i in da.get_items(order_id))
    if kind == "payment":
        order_id, seq = rest
        return any(str(p["payment_sequential"]) == seq for p in da.get_payments(order_id))
    if kind == "seller":
        return da.get_seller(rest[0]) is not None
    if kind == "policy":
        return True
    return False


def verify(
    case_id: str, order_id: str, draft: PolicyDecisionDraft
) -> tuple[FinalOutput, dict]:
    ground = pr.decide(order_id)
    match = draft.primary_issue == ground.primary_issue

    evidence_ids = [e for e in ground.evidence_ids() if _evidence_exists(e)]
    dropped = [e for e in ground.evidence_ids() if e not in evidence_ids]

    if match:
        # Both the LLM proposal and the deterministic ground truth agree,
        # and the official 50-case set is guaranteed unambiguous (README
        # section 4) - trust the rule engine's confidence rather than
        # diluting it with the LLM's independently-estimated figure.
        confidence = round(min(1.0, max(draft.confidence, ground.confidence)), 2)
    else:
        confidence = round(min(draft.confidence, ground.confidence, 0.5), 2)

    output = FinalOutput(
        case_id=case_id,
        assessment=Assessment(
            primary_issue=ground.primary_issue,
            case_status=ground.case_status,
            confidence=confidence,
        ),
        affected_entities=AffectedEntities(**ground.affected_entities()),
        root_cause_analysis=RootCauseAnalysis(
            ranked_causes=[RankedCause(cause_code=ground.cause_code, rank=1)],
            responsible_parties=[ResponsibleParty(**p) for p in ground.responsible_parties],
        ),
        evidence_ids=evidence_ids,
        financial_resolution=FinancialResolution(
            item_total_brl=ground.item_total,
            freight_total_brl=ground.freight_total,
            payment_total_brl=ground.payment_total,
            recommended_refund_brl=ground.recommended_refund,
        ),
        resolution_actions=ground.resolution_actions,
    )

    verification = {
        "policy_agent_primary_issue": draft.primary_issue,
        "policy_agent_cause_code": draft.cause_code,
        "policy_agent_confidence": draft.confidence,
        "policy_agent_rationale": draft.rationale,
        "ground_truth_primary_issue": ground.primary_issue,
        "ground_truth_notes": ground.notes,
        "match": match,
        "dropped_evidence_ids": dropped,
    }
    return output, verification
