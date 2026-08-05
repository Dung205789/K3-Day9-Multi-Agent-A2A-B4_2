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

        # Optional LLM verification pass
        prompt = (
            f"Case ID: {output['case_id']}\n"
            f"Customer Message: {case_input.get('customer_request', {}).get('message', '')}\n"
            f"Assessed Issue: {output['assessment']['primary_issue']}\n"
            f"Recommended Refund BRL: {fin['recommended_refund_brl']}\n"
            f"Verify if primary issue and resolution are logical. Output 'VALID' or 'ADJUST'."
        )
        llm_res = self.llm_client.evaluate_reasoning(prompt)
        if llm_res and "VALID" in llm_res.upper():
            output["assessment"]["confidence"] = min(0.99, output["assessment"]["confidence"] + 0.02)

        return output
