from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Optional
import math

# --- Input Case Schema ---
class CustomerRequest(BaseModel):
    language: str = "vi"
    message: str
    claimed_order_id: str

    class Config:
        extra = "ignore"


class CaseInput(BaseModel):
    case_id: str
    opened_at: str
    customer_request: CustomerRequest
    policy_version: str = "EC_POLICY_V1"

    class Config:
        extra = "ignore"


# --- Output Case Sub-Schemas ---
class Assessment(BaseModel):
    primary_issue: str
    case_status: str  # "action_required" or "no_action"
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator('confidence')
    def clamp_confidence(cls, v):
        return max(0.0, min(1.0, float(round(v, 2))))


class AffectedEntities(BaseModel):
    order_ids: List[str] = Field(default_factory=list)
    item_ids: List[str] = Field(default_factory=list)
    seller_ids: List[str] = Field(default_factory=list)
    payment_ids: List[str] = Field(default_factory=list)

    def enforce_limits_and_clean(self, has_items: bool):
        # Max 5 IDs per entity set
        self.order_ids = list(dict.fromkeys(self.order_ids))[:5]
        self.payment_ids = list(dict.fromkeys(self.payment_ids))[:5]
        if not has_items:
            # If order has no item row, item_ids and seller_ids MUST be empty
            self.item_ids = []
            self.seller_ids = []
        else:
            self.item_ids = list(dict.fromkeys(self.item_ids))[:5]
            self.seller_ids = list(dict.fromkeys(self.seller_ids))[:5]


class RankedCause(BaseModel):
    cause_code: str
    rank: int = 1


class ResponsibleParty(BaseModel):
    party_type: str  # "platform", "seller", "logistics_provider" or None
    party_id: str


class RootCauseAnalysis(BaseModel):
    ranked_causes: List[RankedCause] = Field(default_factory=list)
    responsible_parties: List[ResponsibleParty] = Field(default_factory=list)

    def enforce_limits(self):
        # Max 3 root causes and 3 responsible parties
        self.ranked_causes = self.ranked_causes[:3]
        self.responsible_parties = self.responsible_parties[:3]


class FinancialResolution(BaseModel):
    currency: str = "BRL"
    item_total_brl: float = 0.0
    freight_total_brl: float = 0.0
    payment_total_brl: float = 0.0
    recommended_refund_brl: float = 0.0

    def round_and_clean(self, has_items: bool):
        if not has_items:
            self.item_total_brl = 0.0
            self.freight_total_brl = 0.0
        self.item_total_brl = round(self.item_total_brl, 2)
        self.freight_total_brl = round(self.freight_total_brl, 2)
        self.payment_total_brl = round(self.payment_total_brl, 2)
        self.recommended_refund_brl = round(self.recommended_refund_brl, 2)


# --- Master Output Schema ---
class CaseOutput(BaseModel):
    case_id: str
    assessment: Assessment
    affected_entities: AffectedEntities
    root_cause_analysis: RootCauseAnalysis
    evidence_ids: List[str] = Field(default_factory=list)
    financial_resolution: FinancialResolution
    resolution_actions: List[str] = Field(default_factory=list)

    def finalize_and_enforce_limits(self, has_items: bool = True):
        """Enforce strict array limits, float rounding, and domain rules before submission."""
        self.affected_entities.enforce_limits_and_clean(has_items)
        self.root_cause_analysis.enforce_limits()
        self.financial_resolution.round_and_clean(has_items)
        # Deduplicate and cap evidence IDs to max 10
        self.evidence_ids = list(dict.fromkeys(self.evidence_ids))[:10]
        # Deduplicate and cap resolution actions to max 5
        self.resolution_actions = list(dict.fromkeys(self.resolution_actions))[:5]
        
        # Ensure consistency between refund and case_status
        if self.financial_resolution.recommended_refund_brl > 0:
            self.assessment.case_status = "action_required"
        else:
            self.assessment.case_status = "no_action"
        return self

    def to_submission_dict(self) -> dict:
        """Returns clean dict formatted exactly as required by lab grading engine."""
        return {
            "case_id": self.case_id,
            "assessment": self.assessment.model_dump(),
            "affected_entities": self.affected_entities.model_dump(),
            "root_cause_analysis": {
                "ranked_causes": [rc.model_dump() for rc in self.root_cause_analysis.ranked_causes],
                "responsible_parties": [rp.model_dump() for rp in self.root_cause_analysis.responsible_parties]
            },
            "evidence_ids": self.evidence_ids,
            "financial_resolution": self.financial_resolution.model_dump(),
            "resolution_actions": self.resolution_actions
        }
