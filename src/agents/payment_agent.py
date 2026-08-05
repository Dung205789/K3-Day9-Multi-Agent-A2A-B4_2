from typing import Dict, Any
from src.utils.data_loader import DataLoader

class PaymentAgent:
    def __init__(self, data_loader: DataLoader):
        self.data_loader = data_loader
        self.agent_name = "PaymentAgent"

    def analyze(self, order_id: str, item_total: float, freight_total: float) -> Dict[str, Any]:
        payments = self.data_loader.get_order_payments(order_id)
        
        payment_ids = []
        payment_total = 0.0

        for pay in payments:
            seq = pay.get("payment_sequential")
            val = float(pay.get("payment_value", 0.0))
            payment_ids.append(f"{order_id}:{seq}")
            payment_total += val

        payment_ids.sort(key=lambda x: int(x.split(":")[-1]) if x.split(":")[-1].isdigit() else 1)
        payment_total = round(payment_total, 2)
        total_order_cost = round(item_total + freight_total, 2)
        diff = abs(payment_total - total_order_cost)
        is_reconciled = diff <= 0.10
        has_split_payment = len(payments) >= 2

        return {
            "payment_found": len(payments) > 0,
            "payment_ids": payment_ids[:5],
            "payment_count": len(payments),
            "payment_total_brl": payment_total,
            "has_split_payment": has_split_payment,
            "is_reconciled": is_reconciled,
            "reconciliation_diff": round(diff, 2)
        }
