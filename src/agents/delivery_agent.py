"""Delivery Agent.

Access scope: only the delivery-timeline fields of the orders table
(order_delivered_carrier_date, order_delivered_customer_date,
order_estimated_delivery_date). No item/seller/payment data.
"""

from __future__ import annotations

from datetime import datetime

import data_access as da
import llm_client
from agents.narration import Narration
from schemas import DeliveryFindings

SYSTEM_PROMPT = """Bạn là Delivery Agent trong hệ thống điều tra khiếu nại e-commerce Olist.
Bạn CHỈ được xem các mốc thời gian giao hàng của đơn: ngày carrier nhận hàng, ngày khách nhận
hàng thực tế, ngày giao dự kiến (estimated). Nhiệm vụ: viết 1 câu tóm tắt (tiếng Việt) so sánh
ngày giao thực tế với ngày giao dự kiến, dựa đúng trên kết luận is_late_delivery đã được tính
sẵn từ dữ liệu. Không tự suy luận lại phép so sánh ngày, chỉ diễn giải bằng lời."""


def analyze(order_id: str) -> DeliveryFindings:
    order = da.get_order(order_id)
    if order is None:
        return DeliveryFindings(
            order_id=order_id,
            is_late_delivery=False,
            summary=f"Không tìm thấy order_id {order_id}.",
        )

    carrier = order.get("order_delivered_carrier_date")
    delivered = order.get("order_delivered_customer_date")
    estimated = order.get("order_estimated_delivery_date")

    delivered_dt = _parse(delivered)
    estimated_dt = _parse(estimated)
    is_late = bool(delivered_dt and estimated_dt and delivered_dt > estimated_dt)

    user_prompt = (
        f"order_id: {order_id}\n"
        f"order_delivered_carrier_date: {carrier}\n"
        f"order_delivered_customer_date: {delivered}\n"
        f"order_estimated_delivery_date: {estimated}\n"
        f"is_late_delivery (tính sẵn từ dữ liệu): {is_late}"
    )
    narration = llm_client.structured_call(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=Narration,
    )

    return DeliveryFindings(
        order_id=order_id,
        is_late_delivery=is_late,
        delivered_carrier_date=_clean(carrier),
        delivered_customer_date=_clean(delivered),
        estimated_delivery_date=_clean(estimated),
        summary=narration.summary,
    )


def _clean(v: str | None) -> str | None:
    if v is None or v != v:
        return None
    return v


def _parse(ts: str | None) -> datetime | None:
    if not ts or ts != ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
