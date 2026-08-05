"""Order & Seller agent - owns order status, the item roster and seller handoff."""
from __future__ import annotations

import json

from ..a2a import Message
from ..datastore import money, parse_ts
from .base import JSON_ONLY, Agent, timed

SYSTEM = f"""Bạn là Order & Seller Analyst trong hệ thống xử lý khiếu nại Olist.
Quyền truy cập của bạn: bảng orders, order_items, sellers, products.
Bạn KHÔNG thấy dữ liệu payment và không được suy đoán về tiền đã thanh toán.

Nhiệm vụ:
1. Xác nhận order_status.
2. Liệt kê item và seller thuộc đơn.
3. Với mỗi seller: so sánh order_delivered_carrier_date với shipping_limit_date
   của item thuộc seller đó. Nếu carrier_date > shipping_limit_date thì seller
   bàn giao muộn (late_handoff = true).
4. Cộng price -> item_total_brl, cộng freight_value -> freight_total_brl.

Chỉ dùng dữ liệu được cung cấp. Không bịa order, item, seller không có trong input.
{JSON_ONLY}"""

SCHEMA = """Schema bắt buộc:
{"order_status": str, "item_ids": [str], "seller_ids": [str],
 "late_handoff_seller_ids": [str], "item_total_brl": number,
 "freight_total_brl": number, "handoff_summary": str}
- item_ids dạng "<order_id>:<order_item_id>".
- handoff_summary: 1-2 câu tiếng Việt nêu seller nào bàn giao muộn bao nhiêu."""


class OrderSellerAgent(Agent):
    name = "order_seller"
    role = "Kiểm tra trạng thái đơn, danh sách item/seller và mốc bàn giao carrier"

    @timed
    def handle(self, message: Message) -> Message:
        order_id = message.payload["order_id"]
        order = self.view.order(order_id)

        if order is None:
            return self.bus.send(
                self.name, message.sender, "escalate", "order_not_found",
                {"order_id": order_id, "reason": "order_id không tồn tại trong orders"},
                reply_to=message.msg_id,
            )

        items = self.view.items(order_id)
        carrier = parse_ts(order.get("order_delivered_carrier_date"))

        # Ground truth computed from the rows themselves.
        truth_items = [f"{order_id}:{i['order_item_id']}" for i in items]
        truth_sellers = list(dict.fromkeys(i["seller_id"] for i in items))
        truth_late: list[str] = []
        truth_late_items: list[str] = []
        breach_detail = []
        for it in items:
            limit = parse_ts(it.get("shipping_limit_date"))
            overdue = bool(carrier and limit and carrier > limit)
            if overdue:
                hours = round((carrier - limit).total_seconds() / 3600, 1)
                breach_detail.append(
                    {"seller_id": it["seller_id"], "item": it["order_item_id"],
                     "overdue_hours": hours}
                )
                truth_late_items.append(f"{order_id}:{it['order_item_id']}")
                if it["seller_id"] not in truth_late:
                    truth_late.append(it["seller_id"])
        truth_item_total = money(sum(i["price"] for i in items))
        truth_freight = money(sum(i["freight_value"] for i in items))

        # What the model sees: raw rows only, no precomputed answer.
        prompt = {
            "order_id": order_id,
            "order_status": order.get("order_status"),
            "order_delivered_carrier_date": order.get("order_delivered_carrier_date"),
            "items": [
                {
                    "order_item_id": i["order_item_id"],
                    "seller_id": i["seller_id"],
                    "shipping_limit_date": i["shipping_limit_date"],
                    "price": i["price"],
                    "freight_value": i["freight_value"],
                }
                for i in items
            ],
            "sellers": [
                {k: v for k, v in (self.view.seller(s) or {}).items()}
                for s in truth_sellers
            ],
        }
        data, meta = self.think(
            SYSTEM, json.dumps(prompt, ensure_ascii=False, default=str), SCHEMA
        )

        payload = {
            "order_id": order_id,
            "order_status": self.reconcile(
                "order_status", data.get("order_status"), order.get("order_status")
            ),
            "item_ids": self.reconcile("item_ids", data.get("item_ids"), truth_items),
            "seller_ids": self.reconcile(
                "seller_ids", data.get("seller_ids"), truth_sellers
            ),
            "late_handoff_seller_ids": self.reconcile(
                "late_handoff_seller_ids", data.get("late_handoff_seller_ids"), truth_late
            ),
            "item_total_brl": self.reconcile(
                "item_total_brl", data.get("item_total_brl"), truth_item_total
            ),
            "freight_total_brl": self.reconcile(
                "freight_total_brl", data.get("freight_total_brl"), truth_freight
            ),
            # Which item rows actually breached - the Coordinator needs this to
            # cite the right evidence on a multi-seller order where only some
            # sellers were late.
            "late_handoff_item_ids": truth_late_items,
            "handoff_breaches": breach_detail,
            "seller_handoff_late": bool(truth_late),
            "narrative": data.get("handoff_summary", ""),
            "item_count": len(items),
        }
        return self.bus.send(
            self.name, message.sender, "inform", "order_seller_findings", payload,
            reply_to=message.msg_id,
            tables_read=sorted(set(self.view.reads)),
            divergences=len(self.divergences),
            **meta,
        )
