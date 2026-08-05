from typing import Dict, Any
from src.llm import get_llm

class DeliveryAgent:
    """Specialist Agent responsible for evaluating actual delivery completion against customer promises
    (order_delivered_customer_date vs order_estimated_delivery_date) without timezone conversions.
    """
    def __init__(self):
        self.agent_name = "Delivery Agent"

    def investigate(self, order_seller_facts: Dict[str, Any]) -> Dict[str, Any]:
        order_id = order_seller_facts.get("order_id")
        print(f"[{self.agent_name}] Evaluating Delivery Performance for Order ID: {order_id}")
        
        status = order_seller_facts.get("order_status", "")
        delivered_date = order_seller_facts.get("order_delivered_customer_date", "")
        estimated_date = order_seller_facts.get("order_estimated_delivery_date", "")
        
        # String comparison as dictated by Section 2 of README (no timezone shift required)
        is_late_delivery = False
        if delivered_date and delivered_date != "None" and estimated_date and estimated_date != "None":
            is_late_delivery = (delivered_date > estimated_date)
        elif status == "delivered" and not delivered_date:
            # If marked delivered but date missing, fallback to assumption on-time unless late claim verified
            is_late_delivery = False
            
        delivered_carrier_date = order_seller_facts.get("order_delivered_carrier_date", "")
        seller_handoff_late = order_seller_facts.get("seller_handoff_late", False)
        
        # Determine fault attribution if late
        late_attribution = "none"
        if is_late_delivery:
            if seller_handoff_late:
                late_attribution = "seller"
            else:
                late_attribution = "logistics_provider"
                
        fallback_msg = f"Delivery punctuality check: Late Delivery = {is_late_delivery}, Fault Attribution = '{late_attribution}'."
        llm_prompt = f"Order ID: {order_id}. Customer Delivered Date: {delivered_date}. Estimated Date: {estimated_date}. Is Late Delivery: {is_late_delivery}. Seller Handoff Delayed: {seller_handoff_late}. Fault Attribution: {late_attribution}."
        reasoning = get_llm().generate(
            system_prompt="You are Delivery Specialist Agent in a Multi-Agent team. Summarize delivery timeliness and attribute delay fault between Seller and Logistics Provider in 1-2 factual sentences.",
            user_prompt=llm_prompt,
            fallback_text=fallback_msg
        )

        return {
            "is_late_delivery": is_late_delivery,
            "late_attribution": late_attribution,
            "delivered_customer_date": delivered_date,
            "estimated_delivery_date": estimated_date,
            "delivered_carrier_date": delivered_carrier_date,
            "reasoning_summary": reasoning
        }
