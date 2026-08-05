"""Delivery agent - compares actual delivery against the promised date."""
from __future__ import annotations

import json

from ..a2a import Message
from ..config import LATE_COMPARISON
from ..datastore import delivered_late, parse_ts
from .base import JSON_ONLY, Agent, timed

_LATE_RULE = (
    "delivered_after_estimate = NGÀY của order_delivered_customer_date > NGÀY của "
    "order_estimated_delivery_date. Giao trong cùng ngày cam kết, dù muộn giờ, "
    "vẫn tính là ĐÚNG HẠN."
    if LATE_COMPARISON == "date"
    else "delivered_after_estimate = order_delivered_customer_date > "
         "order_estimated_delivery_date (so trực tiếp cả ngày lẫn giờ)."
)

SYSTEM = f"""Bạn là Delivery Timeline Analyst của Olist.
Quyền truy cập: bảng orders (các mốc thời gian) và order_items (shipping_limit_date).
Bạn KHÔNG thấy dữ liệu payment.

Nhiệm vụ:
1. {_LATE_RULE}
   Nếu một trong hai mốc trống thì = false.
2. Tính số ngày trễ (delay_days), có thể âm nếu giao sớm.
3. carrier_after_shipping_limit = order_delivered_carrier_date > shipping_limit_date
   của ít nhất một item.
4. Xác định blame_hint: "seller" nếu giao trễ VÀ carrier nhận hàng muộn hơn
   shipping_limit_date; "logistics_provider" nếu giao trễ nhưng seller bàn giao
   đúng hạn; "none" nếu không giao trễ.

So sánh trực tiếp giá trị timestamp trong dữ liệu, không đổi múi giờ.
{JSON_ONLY}"""

SCHEMA = """Schema bắt buộc:
{"delivered_after_estimate": bool, "delay_days": number|null,
 "carrier_after_shipping_limit": bool, "blame_hint": "seller"|"logistics_provider"|"none",
 "timeline_summary": str}
- timeline_summary: 1-2 câu tiếng Việt mô tả mốc thời gian."""


class DeliveryAgent(Agent):
    name = "delivery"
    role = "So sánh thời điểm giao thực tế với hạn cam kết và mốc bàn giao carrier"

    @timed
    def handle(self, message: Message) -> Message:
        order_id = message.payload["order_id"]
        order = self.view.order(order_id) or {}
        items = self.view.items(order_id)

        delivered = parse_ts(order.get("order_delivered_customer_date"))
        estimated = parse_ts(order.get("order_estimated_delivery_date"))
        carrier = parse_ts(order.get("order_delivered_carrier_date"))

        late = delivered_late(delivered, estimated)
        delay = (
            round((delivered - estimated).total_seconds() / 86400, 2)
            if delivered and estimated
            else None
        )
        carrier_late = any(
            carrier and parse_ts(i.get("shipping_limit_date"))
            and carrier > parse_ts(i["shipping_limit_date"])
            for i in items
        )
        blame = "none"
        if late:
            blame = "seller" if carrier_late else "logistics_provider"

        prompt = {
            "order_id": order_id,
            "order_status": order.get("order_status"),
            "order_purchase_timestamp": order.get("order_purchase_timestamp"),
            "order_approved_at": order.get("order_approved_at"),
            "order_delivered_carrier_date": order.get("order_delivered_carrier_date"),
            "order_delivered_customer_date": order.get("order_delivered_customer_date"),
            "order_estimated_delivery_date": order.get("order_estimated_delivery_date"),
            "shipping_limit_dates": [
                {"order_item_id": i["order_item_id"],
                 "seller_id": i["seller_id"],
                 "shipping_limit_date": i["shipping_limit_date"]}
                for i in items
            ],
        }
        data, meta = self.think(
            SYSTEM, json.dumps(prompt, ensure_ascii=False, default=str), SCHEMA
        )

        payload = {
            "order_id": order_id,
            "delivered_after_estimate": self.reconcile(
                "delivered_after_estimate", data.get("delivered_after_estimate"), late
            ),
            # Informational only - no policy branch depends on the exact figure.
            "delay_days": self.reconcile(
                "delay_days", data.get("delay_days"), delay, tol=0.6, severity="minor"
            ),
            "carrier_after_shipping_limit": self.reconcile(
                "carrier_after_shipping_limit",
                data.get("carrier_after_shipping_limit"),
                bool(carrier_late),
            ),
            "blame_hint": self.reconcile("blame_hint", data.get("blame_hint"), blame),
            "timeline": {
                "purchase": order.get("order_purchase_timestamp"),
                "approved": order.get("order_approved_at"),
                "carrier": order.get("order_delivered_carrier_date"),
                "delivered": order.get("order_delivered_customer_date"),
                "estimated": order.get("order_estimated_delivery_date"),
            },
            "narrative": data.get("timeline_summary", ""),
        }
        return self.bus.send(
            self.name, message.sender, "inform", "delivery_findings", payload,
            reply_to=message.msg_id,
            tables_read=sorted(set(self.view.reads)),
            divergences=len(self.divergences),
            **meta,
        )
