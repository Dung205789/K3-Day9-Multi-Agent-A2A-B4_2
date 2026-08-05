from typing import Dict, Any, List
from src.config import get_active_model_info
from src.llm import get_llm

class PolicyAgent:
    """Specialist Adjudication Agent responsible for evaluating domain facts against EC_POLICY_V1
    in STRICT priority order (Rules 1 to 6) using models guaranteed <= 10B parameters.
    """
    def __init__(self):
        self.agent_name = "Policy Agent"
        self.model_info = get_active_model_info()
        self._current_claim = ""

    def adjudicate(self, order_facts: Dict[str, Any], payment_facts: Dict[str, Any], delivery_facts: Dict[str, Any], claim_message: str) -> Dict[str, Any]:
        order_id = order_facts.get("order_id")
        self._current_claim = claim_message
        print(f"[{self.agent_name}] Adjudicating Case for Order ID: {order_id} using Model Config (<10B): {self.model_info['model_name']}")
        
        status = order_facts.get("order_status", "")
        item_total = float(order_facts.get("item_total_brl", 0.0))
        freight_total = float(order_facts.get("freight_total_brl", 0.0))
        has_items = order_facts.get("has_items", False)
        
        payment_total = float(payment_facts.get("payment_total_brl", 0.0))
        is_reconciled = payment_facts.get("is_reconciled", True)
        has_split_payments = payment_facts.get("has_split_payments", False)
        
        is_late = delivery_facts.get("is_late_delivery", False)
        seller_handoff_late = order_facts.get("seller_handoff_late", False)
        late_sellers = order_facts.get("late_seller_ids", [])
        all_sellers = order_facts.get("seller_ids", [])

        # Priority Rule 1: canceled_order_paid
        if status == "canceled" and payment_total > 0:
            return self._build_verdict(
                issue="canceled_order_paid",
                cause_code="ORDER_CANCELED_AFTER_PAYMENT",
                party_type="platform",
                party_id="OLIST_PLATFORM",
                refund_brl=payment_total,
                action="issue_full_refund",
                confidence=0.98,
                explanation="Order was canceled after payment had been successfully collected."
            )

        # Priority Rule 2: unavailable_order_paid
        if status == "unavailable" and payment_total > 0:
            return self._build_verdict(
                issue="unavailable_order_paid",
                cause_code="ORDER_UNAVAILABLE_AFTER_PAYMENT",
                party_type="platform",
                party_id="OLIST_PLATFORM",
                refund_brl=payment_total,
                action="issue_full_refund",
                confidence=0.97,
                explanation="Order became unavailable after customer payment was completed."
            )

        # Priority Rule 3: late_delivery_seller
        if is_late and seller_handoff_late:
            violator_id = late_sellers[0] if late_sellers else (all_sellers[0] if all_sellers else "unknown_seller")
            return self._build_verdict(
                issue="late_delivery_seller",
                cause_code="SELLER_HANDOFF_AFTER_LIMIT",
                party_type="seller",
                party_id=violator_id,
                refund_brl=freight_total,
                action="refund_freight",
                confidence=0.94,
                explanation="Order delivered after estimate due to seller handing off items to carrier after shipping_limit_date."
            )

        # Priority Rule 4: late_delivery_logistics
        if is_late and not seller_handoff_late:
            return self._build_verdict(
                issue="late_delivery_logistics",
                cause_code="CARRIER_DELIVERED_AFTER_ESTIMATE",
                party_type="logistics_provider",
                party_id="LOGISTICS_PROVIDER",
                refund_brl=freight_total,
                action="refund_freight",
                confidence=0.93,
                explanation="Order delivered after estimate despite seller handing off items to carrier on time."
            )

        # Priority Rule 5: valid_split_payment
        if has_split_payments and is_reconciled and not is_late and status == "delivered":
            return self._build_verdict(
                issue="valid_split_payment",
                cause_code="MULTIPLE_PAYMENTS_RECONCILED",
                party_type=None,
                party_id=None,
                refund_brl=0.0,
                action="explain_valid_split_payment",
                confidence=0.95,
                explanation="Order payment rows are valid and reconcile with total item and freight value within 0.10 BRL."
            )

        # Priority Rule 6 / Default Fallback: unsupported_late_claim
        return self._build_verdict(
            issue="unsupported_late_claim",
            cause_code="DELIVERY_WITHIN_ESTIMATE",
            party_type=None,
            party_id=None,
            refund_brl=0.0,
            action="reject_late_refund",
            confidence=0.92,
            explanation="Delivery was completed on or before the estimated delivery date; late claim is unsupported by verified data."
        )

    def _build_verdict(self, issue: str, cause_code: str, party_type: str, party_id: str, refund_brl: float, action: str, confidence: float, explanation: str) -> Dict[str, Any]:
        responsible_parties = []
        if party_type and party_id and party_type != "none":
            responsible_parties.append({"party_type": party_type, "party_id": party_id})
            
        llm_prompt = f"Customer Claim: '{self._current_claim}'. Adjudicated Primary Issue: {issue}. Root Cause Code: {cause_code}. Responsible Party: {party_type} ({party_id}). Recommended Refund: {refund_brl} BRL. Action: {action}. Default Legal Note: {explanation}"
        llm_explanation = get_llm().generate(
            system_prompt="You are the Policy Adjudicator Agent enforcing EC_POLICY_V1 priority rules. Provide a 2-sentence formal adjudication statement justifying the decision and resolution based on verified findings.",
            user_prompt=llm_prompt,
            fallback_text=explanation
        )

        return {
            "primary_issue": issue,
            "root_cause_code": cause_code,
            "ranked_causes": [{"cause_code": cause_code, "rank": 1}],
            "responsible_parties": responsible_parties,
            "recommended_refund_brl": round(refund_brl, 2),
            "resolution_actions": [action],
            "confidence": confidence,
            "policy_evidence_id": f"policy:{cause_code}",
            "adjudication_explanation": llm_explanation,
            "model_used": self.model_info["model_name"]
        }
