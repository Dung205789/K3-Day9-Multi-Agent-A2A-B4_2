"""Order & Seller Agent.

Access scope: orders table (status only) + order_items table (items,
seller_id, shipping_limit_date). No payment or delivered/estimated-date
fields are shown to this agent — that belongs to the Payment and Delivery
agents respectively.
"""

from __future__ import annotations

from datetime import datetime

import data_access as da
import llm_client
from agents.narration import Narration
from schemas import OrderSellerFindings

SYSTEM_PROMPT = """Bạn là Order & Seller Agent trong hệ thống điều tra khiếu nại e-commerce Olist.
Bạn CHỈ được xem trạng thái đơn hàng và danh sách item/seller/shipping_limit_date được cung cấp.
Nhiệm vụ: viết 1-2 câu tóm tắt (tiếng Việt) về trạng thái đơn và việc seller nào (nếu có)
đã bàn giao cho carrier sau shipping_limit_date của item họ phụ trách, dựa đúng trên dữ liệu
được cung cấp. Không suy đoán thêm dữ liệu không có trong input."""


def analyze(order_id: str) -> OrderSellerFindings:
    order = da.get_order(order_id)
    if order is None:
        return OrderSellerFindings(
            order_id=order_id,
            order_found=False,
            summary=f"Không tìm thấy order_id {order_id} trong olist_orders_dataset.csv.",
        )

    items = da.get_items(order_id)
    carrier_date = order.get("order_delivered_carrier_date")
    carrier_dt = _parse(carrier_date)

    late_seller_ids: list[str] = []
    for item in items:
        limit_dt = _parse(item.get("shipping_limit_date"))
        if carrier_dt and limit_dt and carrier_dt > limit_dt:
            if item["seller_id"] not in late_seller_ids:
                late_seller_ids.append(item["seller_id"])

    user_prompt = (
        f"order_id: {order_id}\n"
        f"order_status: {order['order_status']}\n"
        f"order_delivered_carrier_date: {carrier_date}\n"
        f"items: {items}\n"
        f"seller(s) đã bàn giao sau shipping_limit_date (tính sẵn từ dữ liệu): {late_seller_ids}"
    )
    narration = llm_client.structured_call(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=Narration,
    )

    return OrderSellerFindings(
        order_id=order_id,
        order_found=True,
        order_status=order["order_status"],
        items=items,
        late_seller_ids=late_seller_ids,
        summary=narration.summary,
    )


def _parse(ts: str | None) -> datetime | None:
    if not ts or ts != ts:  # noqa: PLR0124 - NaN check without importing pandas here
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
