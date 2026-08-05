"""Policy Agent.

Receives only the structured handoff findings from Order&Seller, Delivery
and Payment agents (never raw CSV rows) and applies EC_POLICY_V1 to pick a
primary_issue + root-cause code. Its output is a proposal: the Verifier
Agent cross-checks it against the deterministic rule engine and has final
authority before anything is written to disk.
"""

from __future__ import annotations

import llm_client
from schemas import DeliveryFindings, OrderSellerFindings, PaymentFindings, PolicyDecisionDraft

POLICY_TABLE = """EC_POLICY_V1 - áp dụng theo đúng thứ tự ưu tiên, chỉ chọn 1 primary_issue,
lấy rule đầu tiên (thứ tự trên xuống) mà điều kiện đúng:

1. canceled_order_paid: order_status = canceled VÀ tổng payment > 0
   -> cause_code: ORDER_CANCELED_AFTER_PAYMENT
2. unavailable_order_paid: order_status = unavailable VÀ tổng payment > 0
   -> cause_code: ORDER_UNAVAILABLE_AFTER_PAYMENT
3. late_delivery_seller: is_late_delivery = true VÀ có ít nhất 1 seller trong late_seller_ids
   -> cause_code: SELLER_HANDOFF_AFTER_LIMIT
4. late_delivery_logistics: is_late_delivery = true VÀ late_seller_ids rỗng
   -> cause_code: CARRIER_DELIVERED_AFTER_ESTIMATE
5. valid_split_payment: n_payments >= 2 VÀ reconciled = true (và không rơi vào rule 1-4)
   -> cause_code: MULTIPLE_PAYMENTS_RECONCILED
6. unsupported_late_claim: is_late_delivery = false VÀ reconciled = true (và không rơi vào rule 1-4)
   -> cause_code: DELIVERY_WITHIN_ESTIMATE
"""

SYSTEM_PROMPT = f"""Bạn là Policy Agent, điều phối bởi Coordinator trong hệ thống điều tra khiếu
nại e-commerce Olist. Bạn nhận được các phát hiện (findings) đã được Order&Seller Agent,
Delivery Agent và Payment Agent điều tra sẵn từ dữ liệu thật - không tự bịa thêm sự kiện.

{POLICY_TABLE}

Nhiệm vụ: dựa trên các cờ boolean/số liệu trong findings (order_status, is_late_delivery,
late_seller_ids, n_payments, reconciled), áp dụng đúng bảng trên theo thứ tự ưu tiên và trả về
primary_issue + cause_code tương ứng, cùng confidence [0,1] phản ánh mức chắc chắn và rationale
ngắn gọn bằng tiếng Việt giải thích vì sao chọn rule đó."""


def decide(
    order_seller: OrderSellerFindings,
    delivery: DeliveryFindings,
    payment: PaymentFindings,
    customer_message: str,
) -> PolicyDecisionDraft:
    user_prompt = (
        f"customer_message: {customer_message}\n\n"
        f"order_seller_findings: order_status={order_seller.order_status}, "
        f"late_seller_ids={order_seller.late_seller_ids}, "
        f"order_found={order_seller.order_found}\n"
        f"delivery_findings: is_late_delivery={delivery.is_late_delivery}\n"
        f"payment_findings: n_payments={payment.n_payments}, reconciled={payment.reconciled}, "
        f"payment_total_brl={payment.payment_total_brl}, "
        f"item_plus_freight_brl={payment.item_plus_freight_brl}\n"
    )
    return llm_client.structured_call(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=PolicyDecisionDraft,
    )
