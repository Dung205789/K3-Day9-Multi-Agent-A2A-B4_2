"""Payment agent - reconciles payment rows against item + freight."""
from __future__ import annotations

import json

from ..a2a import Message
from ..config import PAYMENT_TOLERANCE_BRL
from ..datastore import money
from .base import JSON_ONLY, Agent, timed

SYSTEM = f"""Bạn là Payment Reconciliation Analyst của Olist.
Quyền truy cập: bảng order_payments và order_items.
Bạn KHÔNG thấy timestamp giao hàng, không được kết luận đơn giao trễ hay không.

Nhiệm vụ:
1. Cộng payment_value của tất cả payment row -> payment_total_brl.
2. Cộng price + freight_value của item -> expected_total_brl.
3. Tính chênh lệch. Khớp khi |payment_total - expected_total| <= {PAYMENT_TOLERANCE_BRL} BRL.
4. is_split_payment = true khi có từ 2 payment row trở lên.

Lưu ý: payment_value là số tiền của từng payment row, KHÔNG phải giá trị mỗi
installment. Không nhân payment_value với payment_installments.
{JSON_ONLY}"""

SCHEMA = """Schema bắt buộc:
{"payment_ids": [str], "payment_count": int, "payment_total_brl": number,
 "expected_total_brl": number, "gap_brl": number, "payment_matches": bool,
 "is_split_payment": bool, "payment_types": [str], "reconciliation_summary": str}
- payment_ids dạng "<order_id>:<payment_sequential>".
- reconciliation_summary: 1-2 câu tiếng Việt."""


class PaymentAgent(Agent):
    name = "payment"
    role = "Đối soát tổng payment với tổng item + freight, phát hiện split payment"

    @timed
    def handle(self, message: Message) -> Message:
        order_id = message.payload["order_id"]
        payments = self.view.payments(order_id)
        items = self.view.items(order_id)

        truth_ids = [f"{order_id}:{p['payment_sequential']}" for p in payments]
        pay_total = money(sum(p["payment_value"] for p in payments))
        item_total = money(sum(i["price"] for i in items))
        freight_total = money(sum(i["freight_value"] for i in items))
        expected = money(item_total + freight_total)
        gap = money(pay_total - expected)
        matches = abs(pay_total - expected) <= PAYMENT_TOLERANCE_BRL

        prompt = {
            "order_id": order_id,
            "payments": [
                {
                    "payment_sequential": p["payment_sequential"],
                    "payment_type": p["payment_type"],
                    "payment_installments": p["payment_installments"],
                    "payment_value": p["payment_value"],
                }
                for p in payments
            ],
            "items": [
                {
                    "order_item_id": i["order_item_id"],
                    "price": i["price"],
                    "freight_value": i["freight_value"],
                }
                for i in items
            ],
            "tolerance_brl": PAYMENT_TOLERANCE_BRL,
        }
        data, meta = self.think(
            SYSTEM, json.dumps(prompt, ensure_ascii=False, default=str), SCHEMA
        )

        payload = {
            "order_id": order_id,
            "payment_ids": self.reconcile("payment_ids", data.get("payment_ids"), truth_ids),
            "payment_count": self.reconcile(
                "payment_count", data.get("payment_count"), len(payments)
            ),
            "payment_total_brl": self.reconcile(
                "payment_total_brl", data.get("payment_total_brl"), pay_total
            ),
            "item_total_brl": item_total,
            "freight_total_brl": freight_total,
            "expected_total_brl": self.reconcile(
                "expected_total_brl", data.get("expected_total_brl"), expected
            ),
            "gap_brl": self.reconcile("gap_brl", data.get("gap_brl"), gap),
            "payment_matches": self.reconcile(
                "payment_matches", data.get("payment_matches"), matches
            ),
            "is_split_payment": self.reconcile(
                "is_split_payment", data.get("is_split_payment"), len(payments) >= 2
            ),
            "payment_types": list(dict.fromkeys(p["payment_type"] for p in payments)),
            "narrative": data.get("reconciliation_summary", ""),
        }
        return self.bus.send(
            self.name, message.sender, "inform", "payment_findings", payload,
            reply_to=message.msg_id,
            tables_read=sorted(set(self.view.reads)),
            divergences=len(self.divergences),
            **meta,
        )
