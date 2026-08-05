from typing import Dict, Any, List

class PolicyAgent:
    def __init__(self):
        self.agent_name = "PolicyAgent"

    def evaluate(
        self,
        case_id: str,
        order_info: Dict[str, Any],
        payment_info: Dict[str, Any],
        delivery_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        order_id = order_info["order_id"]
        order_status = order_info.get("order_status")
        item_total = order_info.get("item_total_brl", 0.0)
        freight_total = order_info.get("freight_total_brl", 0.0)
        payment_total = payment_info.get("payment_total_brl", 0.0)
        payment_count = payment_info.get("payment_count", 0)

        item_ids = order_info.get("item_ids", [])
        seller_ids = order_info.get("seller_ids", [])
        payment_ids = payment_info.get("payment_ids", [])

        # Priority Rule 1: canceled_order_paid
        if order_status == "canceled" and payment_total > 0:
            primary_issue = "canceled_order_paid"
            root_cause = "ORDER_CANCELED_AFTER_PAYMENT"
            resp_parties = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
            recommended_refund = payment_total
            actions = ["issue_full_refund"]

        # Priority Rule 2: unavailable_order_paid
        elif order_status == "unavailable" and payment_total > 0:
            primary_issue = "unavailable_order_paid"
            root_cause = "ORDER_UNAVAILABLE_AFTER_PAYMENT"
            resp_parties = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
            recommended_refund = payment_total
            actions = ["issue_full_refund"]

        # Priority Rule 3: late_delivery_seller
        elif delivery_info.get("is_customer_delivery_late") and delivery_info.get("has_seller_late_handoff"):
            primary_issue = "late_delivery_seller"
            root_cause = "SELLER_HANDOFF_AFTER_LIMIT"
            violating_sellers = delivery_info.get("late_sellers", [])
            resp_parties = []
            for s_id in violating_sellers[:3]:
                resp_parties.append({"party_type": "seller", "party_id": s_id})
            if not resp_parties and seller_ids:
                resp_parties = [{"party_type": "seller", "party_id": seller_ids[0]}]
            recommended_refund = freight_total
            actions = ["refund_freight"]

        # Priority Rule 4: late_delivery_logistics
        elif delivery_info.get("is_customer_delivery_late") and not delivery_info.get("has_seller_late_handoff"):
            primary_issue = "late_delivery_logistics"
            root_cause = "CARRIER_DELIVERED_AFTER_ESTIMATE"
            resp_parties = [{"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}]
            recommended_refund = freight_total
            actions = ["refund_freight"]

        # Priority Rule 5: valid_split_payment
        elif payment_info.get("has_split_payment") and payment_info.get("is_reconciled"):
            primary_issue = "valid_split_payment"
            root_cause = "MULTIPLE_PAYMENTS_RECONCILED"
            resp_parties = []
            recommended_refund = 0.0
            actions = ["explain_valid_split_payment"]

        # Priority Rule 6: unsupported_late_claim (or default fallback)
        else:
            primary_issue = "unsupported_late_claim"
            root_cause = "DELIVERY_WITHIN_ESTIMATE"
            resp_parties = []
            recommended_refund = 0.0
            actions = ["reject_late_refund"]

        recommended_refund = round(recommended_refund, 2)
        case_status = "action_required" if recommended_refund > 0 else "no_action"
        confidence = 0.95

        # Evidence IDs construction
        evidence_ids = []
        evidence_ids.append(f"order:{order_id}")
        for i_id in item_ids[:3]:
            evidence_ids.append(f"item:{i_id}")
        for p_id in payment_ids[:3]:
            evidence_ids.append(f"payment:{p_id}")
        for s_id in seller_ids[:2]:
            evidence_ids.append(f"seller:{s_id}")
        evidence_ids.append(f"policy:{root_cause}")
        evidence_ids = evidence_ids[:10]

        output = {
            "case_id": case_id,
            "assessment": {
                "primary_issue": primary_issue,
                "case_status": case_status,
                "confidence": confidence
            },
            "affected_entities": {
                "order_ids": [order_id][:5],
                "item_ids": item_ids[:5],
                "seller_ids": seller_ids[:5],
                "payment_ids": payment_ids[:5]
            },
            "root_cause_analysis": {
                "ranked_causes": [
                    {"cause_code": root_cause, "rank": 1}
                ][:3],
                "responsible_parties": resp_parties[:3]
            },
            "evidence_ids": evidence_ids,
            "financial_resolution": {
                "currency": "BRL",
                "item_total_brl": round(item_total, 2),
                "freight_total_brl": round(freight_total, 2),
                "payment_total_brl": round(payment_total, 2),
                "recommended_refund_brl": recommended_refund
            },
            "resolution_actions": actions[:5]
        }

        return output
