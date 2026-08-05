from typing import Dict, Any, List
from src.dataloading import get_db
from src.schema import CaseOutput, Assessment, AffectedEntities, RootCauseAnalysis, RankedCause, ResponsibleParty, FinancialResolution

class VerifierAgent:
    """Specialist Quality Assurance & Critic Agent responsible for protecting against Hard Gate zero-scoring

    by auditing 100% of generated Evidence IDs against raw CSV data and enforcing array size & rounding limits.
    """
    def __init__(self):
        self.db = get_db()
        self.agent_name = "Verifier / Critic Agent"

    def verify_and_format(self, case_id: str, order_facts: Dict[str, Any], payment_facts: Dict[str, Any], policy_verdict: Dict[str, Any]) -> CaseOutput:
        print(f"[{self.agent_name}] Performing Hard Gate QA and verification for Case ID: {case_id}")
        
        has_items = order_facts.get("has_items", False)
        order_id = order_facts.get("order_id", "")
        
        # 1. Gather and audit Evidence IDs (Crucial step: strip any hallucinated or non-existent IDs)
        raw_evidence_ids = []
        if "evidence_ids" in order_facts:
            raw_evidence_ids.extend(order_facts["evidence_ids"])
        if "evidence_ids" in payment_facts:
            raw_evidence_ids.extend(payment_facts["evidence_ids"])
        if "policy_evidence_id" in policy_verdict and policy_verdict["policy_evidence_id"]:
            raw_evidence_ids.append(policy_verdict["policy_evidence_id"])
            
        verified_evidence_ids = []
        for eid in raw_evidence_ids:
            if self.db.check_evidence_exists(eid):
                if eid not in verified_evidence_ids:
                    verified_evidence_ids.append(eid)
            else:
                print(f"[{self.agent_name}] CRITICAL WARNING: Evidence ID '{eid}' failed verification against real CSV dataset. Removed to prevent Hard Gate failure.")
        
        # 2. Build Assessment
        assessment = Assessment(
            primary_issue=policy_verdict["primary_issue"],
            case_status="action_required" if policy_verdict["recommended_refund_brl"] > 0 else "no_action",
            confidence=policy_verdict["confidence"]
        )
        
        # 3. Build Affected Entities
        order_ids = [order_id] if order_id and order_id != "None" else []
        affected = AffectedEntities(
            order_ids=order_ids,
            item_ids=order_facts.get("item_ids", []),
            seller_ids=order_facts.get("seller_ids", []),
            payment_ids=payment_facts.get("payment_ids", [])
        )
        
        # 4. Build Root Cause Analysis
        ranked_causes = [RankedCause(**rc) for rc in policy_verdict.get("ranked_causes", [])]
        responsible_parties = [ResponsibleParty(**rp) for rp in policy_verdict.get("responsible_parties", [])]
        root_cause = RootCauseAnalysis(
            ranked_causes=ranked_causes,
            responsible_parties=responsible_parties
        )
        
        # 5. Build Financial Resolution
        fin = FinancialResolution(
            currency="BRL",
            item_total_brl=order_facts.get("item_total_brl", 0.0),
            freight_total_brl=order_facts.get("freight_total_brl", 0.0),
            payment_total_brl=payment_facts.get("payment_total_brl", 0.0),
            recommended_refund_brl=policy_verdict.get("recommended_refund_brl", 0.0)
        )
        
        # 6. Assemble output model and run finalize enforcement
        output_model = CaseOutput(
            case_id=case_id,
            assessment=assessment,
            affected_entities=affected,
            root_cause_analysis=root_cause,
            evidence_ids=verified_evidence_ids,
            financial_resolution=fin,
            resolution_actions=policy_verdict.get("resolution_actions", [])
        )
        
        return output_model.finalize_and_enforce_limits(has_items=has_items)
