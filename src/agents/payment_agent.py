from typing import Dict, Any, List
from src.dataloading import get_db
from src.llm import get_llm

class PaymentAgent:
    """Specialist Agent responsible for auditing financial records, summing payment rows,
    and reconciling total payments against item and freight costs with a 0.10 BRL threshold.
    """
    def __init__(self):
        self.db = get_db()
        self.agent_name = "Payment Agent"

    def investigate(self, order_id: str, item_total_brl: float, freight_total_brl: float) -> Dict[str, Any]:
        print(f"[{self.agent_name}] Auditing Payments for Order ID: {order_id}")
        payment_rows = self.db.get_order_payments(order_id)
        
        payment_ids: List[str] = []
        evidence_ids: List[str] = []
        payment_total_brl = 0.0
        
        for idx, pay in enumerate(payment_rows):
            seq = str(pay.get("payment_sequential", idx + 1))
            val = float(pay.get("payment_value", 0.0) or 0.0)
            
            pay_id = f"{order_id}:{seq}"
            payment_ids.append(pay_id)
            evidence_ids.append(f"payment:{pay_id}")
            payment_total_brl += val
            
        payment_ids = list(dict.fromkeys(payment_ids))
        evidence_ids = list(dict.fromkeys(evidence_ids))
        
        expected_total = item_total_brl + freight_total_brl
        diff = abs(payment_total_brl - expected_total)
        
        # Reconciled within allowable error margin of 0.10 BRL
        is_reconciled = (diff <= 0.10)
        has_split_payments = (len(payment_rows) >= 2)
        
        fallback_msg = f"Total payment of {payment_total_brl} BRL reconciled with item and freight costs (diff: {round(diff, 2)} BRL, Reconciled: {is_reconciled})."
        llm_prompt = f"Order ID: {order_id}. Payment Total: {payment_total_brl} BRL across {len(payment_rows)} payment records. Expected (Item + Freight): {expected_total} BRL. Difference: {round(diff, 2)} BRL. Within 0.10 BRL tolerance: {is_reconciled}."
        reasoning = get_llm().generate(
            system_prompt="You are Payment Specialist Agent in a Multi-Agent E-commerce Dispute system. Produce a concise 1-2 sentence auditing summary on whether payment records reconcile with total order costs.",
            user_prompt=llm_prompt,
            fallback_text=fallback_msg
        )

        return {
            "payment_ids": payment_ids,
            "payment_total_brl": round(payment_total_brl, 2),
            "payment_row_count": len(payment_rows),
            "is_reconciled": is_reconciled,
            "has_split_payments": has_split_payments,
            "reconciliation_diff_brl": round(diff, 2),
            "evidence_ids": evidence_ids,
            "reasoning_summary": reasoning
        }
