from typing import Dict, Any, List
from src.dataloading import get_db
from src.llm import get_llm

class OrderSellerAgent:
    """Specialist Agent responsible for investigating order status, item inventory, seller identities,
    and verification of carrier handoff compliance (shipping_limit_date vs order_delivered_carrier_date).
    """
    def __init__(self):
        self.db = get_db()
        self.agent_name = "Order & Seller Agent"

    def investigate(self, order_id: str) -> Dict[str, Any]:
        print(f"[{self.agent_name}] Investigating Order ID: {order_id}")
        order_row = self.db.get_order(order_id)
        
        if not order_row:
            return {
                "found": False,
                "order_id": order_id,
                "order_status": "unknown",
                "evidence_ids": [],
                "item_ids": [],
                "seller_ids": [],
                "item_total_brl": 0.0,
                "freight_total_brl": 0.0,
                "has_items": False,
                "seller_handoff_late": False,
                "late_seller_ids": [],
                "reasoning_summary": f"Order ID {order_id} not found in database records."
            }
        
        order_status = str(order_row.get("order_status", "")).strip().lower()
        delivered_carrier_date = str(order_row.get("order_delivered_carrier_date", "")).strip() if order_row.get("order_delivered_carrier_date") else ""
        
        items_rows = self.db.get_order_items(order_id)
        
        item_ids: List[str] = []
        seller_ids: List[str] = []
        evidence_ids: List[str] = [f"order:{order_id}"]
        
        item_total_brl = 0.0
        freight_total_brl = 0.0
        
        seller_handoff_late = False
        late_seller_ids: List[str] = []
        
        for idx, item in enumerate(items_rows):
            order_item_id = str(item.get("order_item_id", idx + 1))
            seller_id = str(item.get("seller_id", "")).strip()
            price = float(item.get("price", 0.0) or 0.0)
            freight = float(item.get("freight_value", 0.0) or 0.0)
            shipping_limit = str(item.get("shipping_limit_date", "")).strip()
            
            item_key = f"{order_id}:{order_item_id}"
            item_ids.append(item_key)
            if seller_id and seller_id != "None":
                seller_ids.append(seller_id)
                evidence_ids.append(f"seller:{seller_id}")
                
            evidence_ids.append(f"item:{item_key}")
            item_total_brl += price
            freight_total_brl += freight
            
            # Check seller handoff delay: string comparison as instructed in README
            if delivered_carrier_date and shipping_limit and delivered_carrier_date > shipping_limit and delivered_carrier_date != "None":
                seller_handoff_late = True
                if seller_id and seller_id not in late_seller_ids:
                    late_seller_ids.append(seller_id)
        
        # Deduplicate preserving order
        item_ids = list(dict.fromkeys(item_ids))
        seller_ids = list(dict.fromkeys(seller_ids))
        evidence_ids = list(dict.fromkeys(evidence_ids))
        
        fallback_msg = f"Order status is '{order_status}' with {len(items_rows)} items. Seller handoff delayed: {seller_handoff_late}."
        llm_prompt = f"Order Status: {order_status}. Carrier Handoff Date: {delivered_carrier_date}. Has Late Seller Handoff: {seller_handoff_late}. Late Seller IDs: {late_seller_ids}. Total Items: {len(items_rows)}."
        reasoning = get_llm().generate(
            system_prompt="You are Order & Seller Specialist Agent in a Multi-Agent Dispute Resolution team. Summarize the order status and seller handoff timeliness in 1-2 factual sentences for handoff to the Coordinator.",
            user_prompt=llm_prompt,
            fallback_text=fallback_msg
        )

        return {
            "found": True,
            "order_id": order_id,
            "order_status": order_status,
            "order_delivered_carrier_date": delivered_carrier_date,
            "order_delivered_customer_date": str(order_row.get("order_delivered_customer_date", "")).strip() if order_row.get("order_delivered_customer_date") else "",
            "order_estimated_delivery_date": str(order_row.get("order_estimated_delivery_date", "")).strip() if order_row.get("order_estimated_delivery_date") else "",
            "has_items": len(items_rows) > 0,
            "item_ids": item_ids,
            "seller_ids": seller_ids,
            "item_total_brl": round(item_total_brl, 2),
            "freight_total_brl": round(freight_total_brl, 2),
            "seller_handoff_late": seller_handoff_late,
            "late_seller_ids": late_seller_ids,
            "evidence_ids": evidence_ids,
            "reasoning_summary": reasoning
        }
