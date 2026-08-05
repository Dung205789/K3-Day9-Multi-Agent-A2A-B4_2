"""Payment Agent.

Access scope: order_payments table + item price/freight (needed only to
reconcile payment_total against item_total + freight_total). No seller or
delivery-date data.
"""

from __future__ import annotations

import data_access as da
import llm_client
from agents.narration import Narration
from schemas import PaymentFindings

MONEY_TOL = 0.10

SYSTEM_PROMPT = """Bạn là Payment Agent trong hệ thống điều tra khiếu nại e-commerce Olist.
Bạn CHỈ được xem danh sách các dòng thanh toán (payment rows) và tổng item + freight của đơn.
Nhiệm vụ: viết 1 câu tóm tắt (tiếng Việt) về việc tổng thanh toán có khớp với tổng item+freight
hay không, dựa đúng trên giá trị reconciled đã tính sẵn từ dữ liệu (sai số cho phép 0.10 BRL).
Không tự làm phép cộng lại, chỉ diễn giải kết quả đã cho."""


def analyze(order_id: str) -> PaymentFindings:
    order = da.get_order(order_id)
    payments = da.get_payments(order_id) if order else []
    items = da.get_items(order_id) if order else []

    payment_total = round(sum(p["payment_value"] for p in payments) + 1e-9, 2)
    item_plus_freight = round(sum(i["price"] + i["freight_value"] for i in items) + 1e-9, 2)
    reconciled = abs(payment_total - item_plus_freight) <= MONEY_TOL

    user_prompt = (
        f"order_id: {order_id}\n"
        f"payments: {payments}\n"
        f"payment_total_brl: {payment_total}\n"
        f"item_plus_freight_brl: {item_plus_freight}\n"
        f"reconciled (tính sẵn từ dữ liệu, sai số 0.10 BRL): {reconciled}"
    )
    narration = llm_client.structured_call(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=Narration,
    )

    return PaymentFindings(
        order_id=order_id,
        payment_total_brl=payment_total,
        item_plus_freight_brl=item_plus_freight,
        reconciled=reconciled,
        n_payments=len(payments),
        summary=narration.summary,
    )
