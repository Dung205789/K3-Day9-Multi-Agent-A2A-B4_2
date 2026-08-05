"""Policy agent - applies EC_POLICY_V1 to the evidence handed over by peers.

Deliberately has *no* database access. It only ever sees the findings the other
agents chose to share, which is exactly the constraint a policy desk works
under. Its verdict is later compared against `src/policy.py` (the deterministic
engine) and any disagreement is surfaced instead of silently overwritten.
"""
from __future__ import annotations

import json

from ..a2a import Message
from ..config import PAYMENT_TOLERANCE_BRL
from .base import JSON_ONLY, Agent, timed

SYSTEM = f"""Bạn là Policy Officer áp dụng EC_POLICY_V1 cho khiếu nại Olist.
Bạn KHÔNG truy cập cơ sở dữ liệu; chỉ dùng bằng chứng do các agent khác bàn giao.

Bảng quy tắc, xét theo đúng thứ tự ưu tiên, luật đầu tiên khớp sẽ thắng:
1. canceled_order_paid - order_status = canceled VÀ payment_total > 0
   -> platform / OLIST_PLATFORM, hoàn = payment_total, action issue_full_refund,
      cause ORDER_CANCELED_AFTER_PAYMENT
2. unavailable_order_paid - order_status = unavailable VÀ payment_total > 0
   -> platform / OLIST_PLATFORM, hoàn = payment_total, action issue_full_refund,
      cause ORDER_UNAVAILABLE_AFTER_PAYMENT
3. late_delivery_seller - delivered_after_estimate = true VÀ
   carrier_after_shipping_limit = true
   -> seller / seller_id vi phạm, hoàn = freight_total, action refund_freight,
      cause SELLER_HANDOFF_AFTER_LIMIT
4. late_delivery_logistics - delivered_after_estimate = true VÀ
   carrier_after_shipping_limit = false
   -> logistics_provider / LOGISTICS_PROVIDER, hoàn = freight_total,
      action refund_freight, cause CARRIER_DELIVERED_AFTER_ESTIMATE
5. valid_split_payment - payment_count >= 2 VÀ payment_matches = true
   -> không có bên chịu trách nhiệm, hoàn = 0, action explain_valid_split_payment,
      cause MULTIPLE_PAYMENTS_RECONCILED
6. unsupported_late_claim - delivered_after_estimate = false VÀ payment_matches = true
   -> không có bên chịu trách nhiệm, hoàn = 0, action reject_late_refund,
      cause DELIVERY_WITHIN_ESTIMATE

case_status = action_required khi refund > 0, ngược lại no_action.
Sai số đối soát thanh toán là {PAYMENT_TOLERANCE_BRL} BRL.
Không được bịa sự kiện không có trong bằng chứng (giao sai hàng, mất hàng,
tracking, refund ledger... đều KHÔNG tồn tại trong dữ liệu Olist).
{JSON_ONLY}"""

SCHEMA = """Schema bắt buộc:
{"primary_issue": str, "case_status": "action_required"|"no_action",
 "root_cause_code": str, "responsible_parties": [{"party_type": str, "party_id": str}],
 "recommended_refund_brl": number, "resolution_actions": [str],
 "rule_number": int, "rationale": str}
- primary_issue thuộc: canceled_order_paid, unavailable_order_paid,
  late_delivery_seller, late_delivery_logistics, valid_split_payment,
  unsupported_late_claim.
- responsible_parties để mảng rỗng khi không có bên chịu trách nhiệm.
- rationale: 2-3 câu tiếng Việt, trích số liệu cụ thể từ bằng chứng."""


class PolicyAgent(Agent):
    name = "policy"
    role = "Áp dụng EC_POLICY_V1 lên bằng chứng đã handoff, quyết định refund và action"

    @timed
    def handle(self, message: Message) -> Message:
        ev = message.payload["evidence_bundle"]
        prompt = {
            "case_id": message.case_id,
            "policy_version": message.payload.get("policy_version"),
            "customer_claim": message.payload.get("customer_claim"),
            "evidence_from_order_seller_agent": ev["order_seller"],
            "evidence_from_payment_agent": ev["payment"],
            "evidence_from_delivery_agent": ev["delivery"],
        }
        data, meta = self.think(
            SYSTEM, json.dumps(prompt, ensure_ascii=False, default=str), SCHEMA,
            max_tokens=800,
        )

        payload = {
            "primary_issue": data.get("primary_issue"),
            "case_status": data.get("case_status"),
            "root_cause_code": data.get("root_cause_code"),
            "responsible_parties": data.get("responsible_parties") or [],
            "recommended_refund_brl": data.get("recommended_refund_brl"),
            "resolution_actions": data.get("resolution_actions") or [],
            "rule_number": data.get("rule_number"),
            "rationale": data.get("rationale", ""),
        }
        return self.bus.send(
            self.name, message.sender, "inform", "policy_verdict", payload,
            reply_to=message.msg_id, tables_read=[], **meta,
        )
