from typing import Dict, Any

class DeliveryAgent:
    def __init__(self):
        self.agent_name = "DeliveryAgent"

    def analyze(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        delivered_cust = order_data.get("order_delivered_customer_date")
        estimated = order_data.get("order_estimated_delivery_date")
        late_sellers = order_data.get("late_sellers", [])

        is_customer_delivery_late = False
        if delivered_cust and estimated:
            if str(delivered_cust) > str(estimated):
                is_customer_delivery_late = True

        has_seller_late_handoff = len(late_sellers) > 0

        return {
            "delivered_customer_date": delivered_cust,
            "estimated_delivery_date": estimated,
            "is_customer_delivery_late": is_customer_delivery_late,
            "has_seller_late_handoff": has_seller_late_handoff,
            "late_sellers": late_sellers
        }
