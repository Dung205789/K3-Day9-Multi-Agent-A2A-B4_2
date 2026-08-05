from typing import Dict, Any
from src.utils.llm_client import LLMClient

class VerifierAgent:
    def __init__(self, llm_client: LLMClient):
        self.agent_name = "VerifierAgent"
        self.llm_client = llm_client

    def verify_and_refine(self, policy_output: Dict[str, Any], case_input: Dict[str, Any]) -> Dict[str, Any]:
        output = policy_output.copy()

        # Enforce limits according to Section 6
        output["affected_entities"]["order_ids"] = output["affected_entities"]["order_ids"][:5]
        output["affected_entities"]["item_ids"] = output["affected_entities"]["item_ids"][:5]
        output["affected_entities"]["seller_ids"] = output["affected_entities"]["seller_ids"][:5]
        output["affected_entities"]["payment_ids"] = output["affected_entities"]["payment_ids"][:5]

        output["root_cause_analysis"]["ranked_causes"] = output["root_cause_analysis"]["ranked_causes"][:3]
        output["root_cause_analysis"]["responsible_parties"] = output["root_cause_analysis"]["responsible_parties"][:3]

        output["evidence_ids"] = output["evidence_ids"][:10]
        output["resolution_actions"] = output["resolution_actions"][:5]

        # Enforce numeric precision and types
        fin = output["financial_resolution"]
        fin["item_total_brl"] = float(round(fin["item_total_brl"], 2))
        fin["freight_total_brl"] = float(round(fin["freight_total_brl"], 2))
        fin["payment_total_brl"] = float(round(fin["payment_total_brl"], 2))
        fin["recommended_refund_brl"] = float(round(fin["recommended_refund_brl"], 2))

        # Enforce case_status consistency
        if fin["recommended_refund_brl"] > 0:
            output["assessment"]["case_status"] = "action_required"
        else:
            output["assessment"]["case_status"] = "no_action"

        # Confidence bounds check
        conf = float(output["assessment"]["confidence"])
        conf = max(0.0, min(1.0, conf))
        output["assessment"]["confidence"] = conf

        # LLM verification pass with complete EC_POLICY_V1 rules
        prompt = (
            f"You are an expert Verifier Agent for Olist E-commerce Dispute Resolution under EC_POLICY_V1.\n"
            f"Case ID: {output['case_id']}\n"
            f"Customer Claim (Translated): {case_input.get('customer_request', {}).get('message', '')}\n"
            f"Proposed Resolution:\n"
            f"  - Primary Issue: {output['assessment']['primary_issue']}\n"
            f"  - Recommended Refund BRL: {fin['recommended_refund_brl']}\n"
            f"  - Responsible Parties: {output['root_cause_analysis']['responsible_parties']}\n"
            f"  - Resolution Actions: {output['resolution_actions']}\n"
            f"  - Evidence IDs: {output['evidence_ids']}\n\n"
            f"EC_POLICY_V1 Priority Rules:\n"
            f"1. canceled_order_paid (canceled order + payment > 0) -> refund full payment\n"
            f"2. unavailable_order_paid (unavailable order + payment > 0) -> refund full payment\n"
            f"3. late_delivery_seller (delivered late + seller handoff late) -> refund freight\n"
            f"4. late_delivery_logistics (delivered late + seller handoff on time) -> refund freight\n"
            f"5. valid_split_payment (2+ payments, reconciled) -> 0 refund\n"
            f"6. unsupported_late_claim (delivered on time) -> 0 refund\n\n"
            f"Check if the assessment strictly matches rules and evidence. Reply 'VALID' if correct along with a confidence score between 0.80 and 0.98 (e.g., 'VALID 0.95')."
        )
        llm_res = self.llm_client.evaluate_reasoning(prompt)
        if llm_res:
            res_upper = llm_res.upper()
            if "VALID" in res_upper:
                # Try extracting float score from LLM output if provided
                import re
                scores = re.findall(r"0\.\d+", llm_res)
                if scores:
                    parsed_conf = float(scores[0])
                    output["assessment"]["confidence"] = max(0.80, min(0.98, parsed_conf))
                else:
                    output["assessment"]["confidence"] = 0.95

        return output
