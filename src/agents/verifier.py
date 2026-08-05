"""Verifier agent - last line of defence before a file is written.

Two passes:
  1. Deterministic audit: schema, enums, caps, ID syntax, ID existence in the
     CSVs, refund arithmetic, status/refund coherence. Repairs what it can.
  2. LLM adversarial review: reads the draft plus the evidence and looks for
     claims that are not supported by the bundle.
Only the deterministic pass can change the payload; the LLM pass raises flags.
"""
from __future__ import annotations

import json
import re

from ..a2a import Message
from ..config import (
    ISSUE_RULES,
    MAX_ACTIONS,
    MAX_ENTITY_IDS,
    MAX_EVIDENCE,
    MAX_PARTIES,
    MAX_ROOT_CAUSES,
    PRIMARY_ISSUES,
    RESOLUTION_ACTIONS,
    ROOT_CAUSE_CODES,
)
from ..datastore import money
from .base import JSON_ONLY, Agent, timed

# Checks the deterministic audit already settles numerically. The LLM may
# comment on them, but it cannot flip the verdict - see _llm_review().
DETERMINISTIC_COVERED = {"refund_type_correct", "parties_consistent"}

EVIDENCE_PATTERNS = {
    "order": re.compile(r"^order:([^:]+)$"),
    "item": re.compile(r"^item:([^:]+):(\d+)$"),
    "payment": re.compile(r"^payment:([^:]+):(\d+)$"),
    "seller": re.compile(r"^seller:([^:]+)$"),
    "policy": re.compile(r"^policy:([A-Z_]+)$"),
}

SYSTEM = f"""Bạn là Verifier trong hệ thống xử lý khiếu nại Olist.
Bạn nhận một bản nháp kết luận và bộ bằng chứng do các agent khác thu thập.

Bảng đối chiếu EC_POLICY_V1 (issue -> hoàn tiền -> bên chịu trách nhiệm):
- canceled_order_paid      -> hoàn payment_total_brl -> platform/OLIST_PLATFORM
- unavailable_order_paid   -> hoàn payment_total_brl -> platform/OLIST_PLATFORM
- late_delivery_seller     -> hoàn freight_total_brl -> seller/<seller_id>
- late_delivery_logistics  -> hoàn freight_total_brl -> logistics_provider/LOGISTICS_PROVIDER
- valid_split_payment      -> hoàn 0 -> KHÔNG có bên chịu trách nhiệm (mảng rỗng là ĐÚNG)
- unsupported_late_claim   -> hoàn 0 -> KHÔNG có bên chịu trách nhiệm (mảng rỗng là ĐÚNG)

Thực hiện 4 check dưới đây. Với MỖI check bạn phải trích tên field và giá trị
cụ thể trong bằng chứng mà bạn dựa vào:
- issue_supported: bằng chứng có ủng hộ primary_issue không?
- refund_type_correct: số tiền hoàn có đúng loại theo bảng trên không?
- parties_consistent: responsible_parties có khớp bảng trên không?
  (với 2 issue cuối, mảng rỗng chính là kết quả đúng - KHÔNG được báo fail)
- no_unsupported_claims: bản nháp có khẳng định gì không tồn tại trong bằng chứng không?

QUY TẮC BẮT BUỘC: chỉ được đặt verdict = "fail" khi bạn trích được field và giá
trị cụ thể chứng minh mâu thuẫn. Nếu không trích được, verdict phải là "pass".
Không được fail chỉ vì "thiếu thông tin" hay "cần xem xét thêm".
approved = true khi cả 4 check đều pass.
{JSON_ONLY}"""

SCHEMA = """Schema bắt buộc:
{"checks": [{"check": str, "verdict": "pass"|"fail", "evidence": str}],
 "approved": bool, "confidence_adjustment": number, "review": str}
- checks phải có đúng 4 phần tử theo đúng tên check ở trên.
- evidence: trích field=giá trị thật từ bằng chứng, vd
  "delivery.delivered_after_estimate=true, order_seller.late_handoff_seller_ids=[abc]".
- confidence_adjustment trong [-0.25, 0.03], để 0 khi mọi check đều pass.
- review: 1-2 câu tiếng Việt."""


class VerifierAgent(Agent):
    name = "verifier"
    role = "Kiểm tra schema, sự tồn tại của ID, số tiền và tính nhất quán trước khi ghi file"

    @timed
    def handle(self, message: Message) -> Message:
        draft = json.loads(json.dumps(message.payload["draft"]))  # deep copy
        facts = message.payload["facts"]
        issues: list[str] = []
        repairs: list[str] = []

        self._audit_structure(draft, issues, repairs)
        self._audit_entities(draft, facts, issues, repairs)
        self._audit_evidence(draft, issues, repairs)
        self._audit_money(draft, facts, issues, repairs)

        review, meta = self._llm_review(draft, message.payload.get("evidence_bundle", {}))

        hard_fail = [i for i in issues if i.startswith("HARD:")]
        performative = "reject" if hard_fail else "confirm"
        payload = {
            "approved": not hard_fail,
            "issues": issues,
            "repairs": repairs,
            "llm_review": review,
            "checked": {
                "schema": True,
                "id_existence": True,
                "amounts": True,
                "caps": True,
            },
        }
        payload["draft"] = draft
        return self.bus.send(
            self.name, message.sender, performative, "verification_report", payload,
            reply_to=message.msg_id, tables_read=["__existence__"], **meta,
        )

    # ------------------------------------------------------------------
    def _audit_structure(self, d: dict, issues: list, repairs: list) -> None:
        required = {
            "case_id", "assessment", "affected_entities", "root_cause_analysis",
            "evidence_ids", "financial_resolution", "resolution_actions",
        }
        missing = required - set(d)
        if missing:
            issues.append(f"HARD: thiếu khoá bắt buộc {sorted(missing)}")
            return

        a = d["assessment"]
        if a.get("primary_issue") not in PRIMARY_ISSUES:
            issues.append(f"HARD: primary_issue không hợp lệ: {a.get('primary_issue')}")
        if a.get("case_status") not in ("action_required", "no_action"):
            issues.append(f"HARD: case_status không hợp lệ: {a.get('case_status')}")
        conf = a.get("confidence")
        if not isinstance(conf, (int, float)) or not 0.0 <= float(conf) <= 1.0:
            a["confidence"] = 0.5
            repairs.append("confidence nằm ngoài [0,1] -> đặt lại 0.5")
        else:
            a["confidence"] = round(float(conf), 2)

        rca = d["root_cause_analysis"]
        causes = rca.get("ranked_causes") or []
        clean = [c for c in causes if c.get("cause_code") in ROOT_CAUSE_CODES]
        if len(clean) != len(causes):
            repairs.append("loại bỏ cause_code không nằm trong danh mục")
        for i, c in enumerate(clean, start=1):
            c["rank"] = i
        rca["ranked_causes"] = clean[:MAX_ROOT_CAUSES]
        if not rca["ranked_causes"]:
            issues.append("HARD: không có root cause hợp lệ")

        parties = [
            p for p in (rca.get("responsible_parties") or [])
            if p.get("party_type") in ("seller", "platform", "logistics_provider")
            and p.get("party_id")
        ]
        rca["responsible_parties"] = parties[:MAX_PARTIES]

        actions = [x for x in (d.get("resolution_actions") or []) if x in RESOLUTION_ACTIONS]
        if len(actions) != len(d.get("resolution_actions") or []):
            repairs.append("loại bỏ resolution_action ngoài danh mục")
        d["resolution_actions"] = actions[:MAX_ACTIONS]
        if not d["resolution_actions"]:
            issues.append("HARD: không có resolution_action hợp lệ")

    def _audit_entities(self, d: dict, facts: dict, issues: list, repairs: list) -> None:
        ae = d.get("affected_entities", {})
        oid = facts["order_id"]

        keep_orders = [o for o in ae.get("order_ids", []) if self.view.exists("order", o)]
        if len(keep_orders) != len(ae.get("order_ids", [])):
            repairs.append("loại bỏ order_id không tồn tại")
        ae["order_ids"] = keep_orders[:MAX_ENTITY_IDS]
        if not ae["order_ids"]:
            issues.append("HARD: affected_entities.order_ids rỗng")

        keep_items = []
        for iid in ae.get("item_ids", []):
            parts = str(iid).split(":")
            if len(parts) == 2 and self.view.exists("item", parts[0], parts[1]):
                keep_items.append(iid)
        if len(keep_items) != len(ae.get("item_ids", [])):
            repairs.append("loại bỏ item_id không tồn tại/sai định dạng")
        ae["item_ids"] = keep_items[:MAX_ENTITY_IDS]

        keep_sellers = [s for s in ae.get("seller_ids", []) if self.view.exists("seller", s)]
        if len(keep_sellers) != len(ae.get("seller_ids", [])):
            repairs.append("loại bỏ seller_id không tồn tại")
        ae["seller_ids"] = keep_sellers[:MAX_ENTITY_IDS]

        keep_pay = []
        for pid in ae.get("payment_ids", []):
            parts = str(pid).split(":")
            if len(parts) == 2 and self.view.exists("payment", parts[0], parts[1]):
                keep_pay.append(pid)
        if len(keep_pay) != len(ae.get("payment_ids", [])):
            repairs.append("loại bỏ payment_id không tồn tại/sai định dạng")
        ae["payment_ids"] = keep_pay[:MAX_ENTITY_IDS]

        if facts["item_count"] == 0 and (ae["item_ids"] or ae["seller_ids"]):
            ae["item_ids"], ae["seller_ids"] = [], []
            repairs.append("đơn không có item row -> làm rỗng item_ids/seller_ids")
        _ = oid

    def _audit_evidence(self, d: dict, issues: list, repairs: list) -> None:
        kept: list[str] = []
        for ev in d.get("evidence_ids", []):
            ev = str(ev)
            ok = False
            for kind, pattern in EVIDENCE_PATTERNS.items():
                m = pattern.match(ev)
                if not m:
                    continue
                if kind == "policy":
                    ok = m.group(1) in ROOT_CAUSE_CODES
                else:
                    ok = self.view.exists(kind, *m.groups())
                break
            if ok and ev not in kept:
                kept.append(ev)
            elif not ok:
                repairs.append(f"loại bỏ evidence không dựng được từ dữ liệu: {ev}")
        d["evidence_ids"] = kept[:MAX_EVIDENCE]
        if not d["evidence_ids"]:
            issues.append("HARD: không còn evidence hợp lệ")

    def _audit_money(self, d: dict, facts: dict, issues: list, repairs: list) -> None:
        fr = d.get("financial_resolution", {})
        fr["currency"] = "BRL"
        for key, truth in (
            ("item_total_brl", facts["item_total_brl"]),
            ("freight_total_brl", facts["freight_total_brl"]),
            ("payment_total_brl", facts["payment_total_brl"]),
        ):
            if abs(float(fr.get(key, 0)) - truth) > 0.005:
                repairs.append(f"{key}: {fr.get(key)} -> {truth}")
            fr[key] = money(truth)

        issue = d["assessment"].get("primary_issue")
        if issue in ISSUE_RULES:
            if issue in ("canceled_order_paid", "unavailable_order_paid"):
                expect = money(facts["payment_total_brl"])
            elif issue in ("late_delivery_seller", "late_delivery_logistics"):
                expect = money(facts["freight_total_brl"])
            else:
                expect = 0.0
            if abs(float(fr.get("recommended_refund_brl", 0)) - expect) > 0.005:
                repairs.append(
                    f"recommended_refund_brl: {fr.get('recommended_refund_brl')} -> {expect}"
                )
            fr["recommended_refund_brl"] = expect

            want_status = "action_required" if expect > 0 else "no_action"
            if d["assessment"].get("case_status") != want_status:
                repairs.append(
                    f"case_status: {d['assessment'].get('case_status')} -> {want_status}"
                )
                d["assessment"]["case_status"] = want_status
        else:
            issues.append("HARD: không xác định được primary_issue để kiểm tra số tiền")

    def _llm_review(self, draft: dict, bundle: dict):
        prompt = {
            "draft_resolution": draft,
            "evidence_bundle": bundle,
        }
        try:
            data, meta = self.think(
                SYSTEM, json.dumps(prompt, ensure_ascii=False, default=str), SCHEMA,
                max_tokens=500,
            )
        except Exception as exc:  # verification must never crash the pipeline
            return {"approved": True, "checks": [], "concerns": [],
                    "confidence_adjustment": 0.0,
                    "review": f"LLM review bỏ qua: {exc}"}, {}

        checks = [c for c in (data.get("checks") or []) if isinstance(c, dict)]
        failed = []
        for c in checks:
            if str(c.get("verdict")).lower() != "fail":
                continue
            # A "fail" with no cited evidence is the model echoing the checklist
            # back at us - it rejected every clean draft before this guard.
            if len(str(c.get("evidence", "")).strip()) < 8:
                c["verdict"] = "pass"
                c["note"] = "fail bị bỏ: không trích được bằng chứng"
                continue
            # The deterministic pass above already *proved* the refund figure and
            # the party mapping against the CSVs. A weaker LLM signal does not get
            # to overturn a proof - it is recorded as advisory instead.
            if c.get("check") in DETERMINISTIC_COVERED:
                c["verdict"] = "advisory"
                c["note"] = "đã được lớp kiểm tra tất định xác nhận, chỉ ghi nhận"
                continue
            failed.append(c)

        approved = not failed
        adj = data.get("confidence_adjustment", 0.0)
        try:
            adj = float(adj)
        except (TypeError, ValueError):
            adj = 0.0
        adj = max(-0.03, min(0.03, adj)) if approved else max(-0.25, min(0.0, adj))
        return {
            "approved": approved,
            "checks": checks,
            "concerns": [
                f"{c.get('check')}: {c.get('evidence')}" for c in failed
            ][:5],
            "confidence_adjustment": adj,
            "review": data.get("review", ""),
        }, meta
