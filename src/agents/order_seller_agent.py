from typing import Dict, Any, List
from src.utils.data_loader import DataLoader

class OrderSellerAgent:
    def __init__(self, data_loader: DataLoader):
        self.data_loader = data_loader
        self.agent_name = "OrderSellerAgent"

    def analyze(self, order_id: str) -> Dict[str, Any]:
        order = self.data_loader.get_order(order_id)
        items = self.data_loader.get_order_items(order_id)

        if not order:
            return {
                "order_found": False,
                "order_id": order_id,
                "order_status": None,
                "items": [],
                "seller_ids": [],
                "item_ids": [],
                "item_total_brl": 0.0,
                "freight_total_brl": 0.0,
                "order_delivered_carrier_date": None,
                "order_delivered_customer_date": None,
                "order_estimated_delivery_date": None,
                "late_sellers": []
            }

        item_ids = []
        seller_ids = []
        item_total = 0.0
        freight_total = 0.0
        late_sellers = []

        carrier_date_str = order.get("order_delivered_carrier_date")
        
        for item in items:
            item_seq = item.get("order_item_id")
            seller_id = str(item.get("seller_id"))
            price = float(item.get("price", 0.0))
            freight = float(item.get("freight_value", 0.0))
            shipping_limit = item.get("shipping_limit_date")

            item_id_str = f"{order_id}:{item_seq}"
            item_ids.append(item_id_str)
            if seller_id and seller_id not in seller_ids:
                seller_ids.append(seller_id)

            item_total += price
            freight_total += freight

            # Check seller late handoff: carrier date > shipping limit date
            if carrier_date_str and shipping_limit:
                if str(carrier_date_str) > str(shipping_limit):
                    if seller_id not in late_sellers:
                        late_sellers.append(seller_id)

        item_ids.sort(key=lambda x: int(x.split(":")[-1]) if x.split(":")[-1].isdigit() else 1)

        return {
            "order_found": True,
            "order_id": order_id,
            "order_status": order.get("order_status"),
            "items": items,
            "seller_ids": seller_ids[:5],
            "item_ids": item_ids[:5],
            "item_total_brl": round(item_total, 2),
            "freight_total_brl": round(freight_total, 2),
            "order_delivered_carrier_date": carrier_date_str,
            "order_delivered_customer_date": order.get("order_delivered_customer_date"),
            "order_estimated_delivery_date": order.get("order_estimated_delivery_date"),
            "late_sellers": late_sellers
        }
