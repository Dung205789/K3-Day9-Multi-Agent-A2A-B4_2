"""Coordinator - triages the claim, dispatches specialists, assembles the answer.

Has no database scope of its own: every fact in the final JSON arrived through
an A2A message from an agent that was allowed to read the table it came from.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from ..a2a import Bus, Message
from ..config import MAX_ENTITY_IDS, POLICY_VERSION
from ..datastore import DataStore
from .base import JSON_ONLY, Agent, timed
from .delivery import DeliveryAgent
from .order_seller import OrderSellerAgent
from .payment import PaymentAgent
from .policy_agent import PolicyAgent
from .verifier import VerifierAgent

TRIAGE_SYSTEM = f"""Bạn là Coordinator của tổ xử lý khiếu nại Olist.
Bạn nhận nội dung khiếu nại bằng ngôn ngữ tự nhiên và phải phân loại sơ bộ,
sau đó giao việc cho các chuyên gia.

Các chuyên gia hiện có:
- order_seller: trạng thái đơn, item, seller, mốc bàn giao carrier
- payment: đối soát payment với item + freight
- delivery: so sánh thời điểm giao thực tế với hạn cam kết

Lưu ý: lời khiếu nại của khách CHƯA chắc đúng. Nhiệm vụ của bạn là nêu giả
thuyết cần kiểm chứng, không phải kết luận.
{JSON_ONLY}"""

TRIAGE_SCHEMA = """Schema bắt buộc:
{"claim_type": str, "hypotheses": [str], "dispatch": [str], "triage_note": str}
- claim_type: tóm tắt ngắn loại khiếu nại khách nêu (vd "giao trễ").
- hypotheses: tối đa 3 giả thuyết cần kiểm chứng.
- dispatch: danh sách agent cần huy động.
- triage_note: 1 câu tiếng Việt."""

SUMMARY_SYSTEM = f"""Bạn là Coordinator tổng hợp kết luận cuối cho một case khiếu nại Olist.
Bạn nhận: kết luận của Policy agent, kết quả đối chiếu với rule engine tất định,
và báo cáo của Verifier.

Viết bản tóm tắt cho nhân viên CSKH: nêu rõ vấn đề chính, bên chịu trách nhiệm,
số tiền hoàn và lý do, dựa trên số liệu có thật. Không bịa thêm sự kiện.
Đánh giá độ tin cậy: cao khi Policy agent và rule engine đồng thuận và Verifier
không có cảnh báo; thấp hơn khi có bất đồng.
{JSON_ONLY}"""

SUMMARY_SCHEMA = """Schema bắt buộc:
{"customer_summary": str, "internal_note": str, "confidence": number}
- customer_summary: 2-3 câu tiếng Việt, lịch sự, nêu kết quả xử lý.
- internal_note: 1-2 câu cho nội bộ, nêu bằng chứng quyết định.
- confidence: số trong [0,1]."""


class CoordinatorAgent(Agent):
    name = "coordinator"
    role = "Phân loại khiếu nại, giao việc, tổng hợp và chốt kết quả"

    def __init__(self, store: DataStore, bus: Bus):
        super().__init__(store, bus)
        self.workers = {
            "order_seller": OrderSellerAgent(store, bus),
            "payment": PaymentAgent(store, bus),
            "delivery": DeliveryAgent(store, bus),
        }
        self.policy_agent = PolicyAgent(store, bus)
        self.verifier = VerifierAgent(store, bus)

    # ------------------------------------------------------------------
    def triage(self, case: dict) -> dict:
        req = case.get("customer_request", {})
        prompt = {
            "case_id": case.get("case_id"),
            "opened_at": case.get("opened_at"),
            "language": req.get("language"),
            "message": req.get("message"),
            "claimed_order_id": req.get("claimed_order_id"),
        }
        try:
            data, meta = self.think(
                TRIAGE_SYSTEM, json.dumps(prompt, ensure_ascii=False), TRIAGE_SCHEMA,
                max_tokens=400,
            )
        except Exception as exc:
            data, meta = (
                {"claim_type": "unknown", "hypotheses": [], "dispatch": list(self.workers),
                 "triage_note": f"triage lỗi: {exc}"},
                {},
            )
        data["dispatch"] = [a for a in (data.get("dispatch") or []) if a in self.workers]
        self.bus.send(
            self.name, "broadcast", "inform", "triage", data,
            requested=list(self.workers), **meta,
        )
        return data

    def dispatch(self, order_id: str, case_id: str) -> dict[str, Message]:
        """Fan out to the three domain agents in parallel and collect replies."""
        requests: dict[str, Message] = {}
        for name in self.workers:
            requests[name] = self.bus.send(
                self.name, name, "request", "investigate",
                {"order_id": order_id, "case_id": case_id},
            )

        replies: dict[str, Message] = {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                name: pool.submit(agent.handle, requests[name])
                for name, agent in self.workers.items()
            }
            for name, fut in futures.items():
                replies[name] = fut.result()
        return replies

    def to_policy(self, case: dict, bundle: dict) -> Message:
        req = self.bus.send(
            self.name, "policy", "handoff", "apply_policy",
            {
                "evidence_bundle": bundle,
                "policy_version": case.get("policy_version", POLICY_VERSION),
                "customer_claim": case.get("customer_request", {}).get("message"),
            },
        )
        return self.policy_agent.handle(req)

    def to_verifier(self, draft: dict, facts: dict, bundle: dict) -> Message:
        req = self.bus.send(
            self.name, "verifier", "handoff", "verify_draft",
            {"draft": draft, "facts": _slim_facts(facts), "evidence_bundle": bundle},
        )
        return self.verifier.handle(req)

    @timed
    def summarize(self, context: dict) -> Message:
        try:
            data, meta = self.think(
                SUMMARY_SYSTEM, json.dumps(context, ensure_ascii=False, default=str),
                SUMMARY_SCHEMA, max_tokens=450,
            )
        except Exception as exc:
            data, meta = (
                {"customer_summary": "", "internal_note": f"summary lỗi: {exc}",
                 "confidence": 0.8},
                {},
            )
        return self.bus.send(
            self.name, "case_file", "inform", "final_summary", data, **meta
        )


def _slim_facts(facts: dict) -> dict:
    """Facts the verifier needs, without shipping the whole row dump around."""
    return {
        k: facts[k]
        for k in (
            "order_id", "order_status", "item_count", "payment_count",
            "item_total_brl", "freight_total_brl", "payment_total_brl",
            "expected_total_brl", "payment_matches", "delivered_after_estimate",
            "carrier_after_shipping_limit", "late_seller_ids", "seller_ids",
        )
    }


def cap(seq, limit: int = MAX_ENTITY_IDS) -> list:
    out: list = []
    for x in seq or []:
        if x not in out:
            out.append(x)
    return out[:limit]
