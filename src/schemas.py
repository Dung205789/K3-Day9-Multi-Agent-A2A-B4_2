"""Pydantic models: the final README output schema plus the structured
handoff messages agents pass to each other via the Coordinator."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

PRIMARY_ISSUES = (
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
)


# ---------------------------------------------------------------------------
# Handoff messages between worker agents and the Coordinator
# ---------------------------------------------------------------------------


class OrderSellerFindings(BaseModel):
    order_id: str
    order_found: bool
    order_status: str | None = None
    items: list[dict] = Field(default_factory=list)
    late_seller_ids: list[str] = Field(default_factory=list)
    summary: str = ""


class DeliveryFindings(BaseModel):
    order_id: str
    is_late_delivery: bool
    delivered_carrier_date: str | None = None
    delivered_customer_date: str | None = None
    estimated_delivery_date: str | None = None
    summary: str = ""


class PaymentFindings(BaseModel):
    order_id: str
    payment_total_brl: float
    item_plus_freight_brl: float
    reconciled: bool
    n_payments: int
    summary: str = ""


class PolicyDecisionDraft(BaseModel):
    primary_issue: Literal[PRIMARY_ISSUES]
    cause_code: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


# ---------------------------------------------------------------------------
# Final output schema (README.md section 6)
# ---------------------------------------------------------------------------


def _capped(max_len: int):
    def _validator(v: list) -> list:
        return v[:max_len]

    return _validator


class Assessment(BaseModel):
    primary_issue: Literal[PRIMARY_ISSUES]
    case_status: Literal["action_required", "no_action"]
    confidence: float = Field(ge=0.0, le=1.0)


class AffectedEntities(BaseModel):
    order_ids: list[str] = Field(default_factory=list, max_length=5)
    item_ids: list[str] = Field(default_factory=list, max_length=5)
    seller_ids: list[str] = Field(default_factory=list, max_length=5)
    payment_ids: list[str] = Field(default_factory=list, max_length=5)


class RankedCause(BaseModel):
    cause_code: str
    rank: int


class ResponsibleParty(BaseModel):
    party_type: str
    party_id: str


class RootCauseAnalysis(BaseModel):
    ranked_causes: list[RankedCause] = Field(default_factory=list, max_length=3)
    responsible_parties: list[ResponsibleParty] = Field(default_factory=list, max_length=3)


class FinancialResolution(BaseModel):
    currency: Literal["BRL"] = "BRL"
    item_total_brl: float
    freight_total_brl: float
    payment_total_brl: float
    recommended_refund_brl: float


class FinalOutput(BaseModel):
    case_id: str
    assessment: Assessment
    affected_entities: AffectedEntities
    root_cause_analysis: RootCauseAnalysis
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)
    financial_resolution: FinancialResolution
    resolution_actions: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("evidence_ids", "resolution_actions")
    @classmethod
    def _non_empty_strings(cls, v: list[str]) -> list[str]:
        return [s for s in v if s]
