"""EC_POLICY_V1 - the deterministic rule engine.

This module is the written-down version of README section 4. The Policy agent
reasons about the same rules in natural language; this engine is what the
Verifier agent checks that reasoning against. Keeping the two separate is the
point: an LLM that hallucinates a refund gets caught here.
"""
from __future__ import annotations

from .config import ISSUE_RULES, PAYMENT_TOLERANCE_BRL
from .datastore import money

# Priority order straight from the spec table - first match wins.
PRIORITY = [
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
]

ISSUE_LABELS = {
    "canceled_order_paid": "Đơn bị hủy nhưng đã thanh toán",
    "unavailable_order_paid": "Đơn unavailable nhưng đã thanh toán",
    "late_delivery_seller": "Giao trễ - lỗi seller bàn giao muộn",
    "late_delivery_logistics": "Giao trễ - lỗi đơn vị vận chuyển",
    "valid_split_payment": "Thanh toán tách nhiều lần, đã đối soát khớp",
    "unsupported_late_claim": "Khiếu nại giao trễ không có cơ sở",
}


def evaluate(facts: dict) -> dict:
    """Apply EC_POLICY_V1 to a fact sheet. Returns the full resolution."""
    if not facts.get("found"):
        return {
            "primary_issue": None,
            "matched_rule": None,
            "checks": [],
            "reason": "order_id không tồn tại trong dữ liệu Olist",
        }

    status = (facts.get("order_status") or "").lower()
    payment_total = facts["payment_total_brl"]
    freight_total = facts["freight_total_brl"]
    item_total = facts["item_total_brl"]
    late = facts["delivered_after_estimate"]
    seller_late = facts["carrier_after_shipping_limit"]
    n_payments = facts["payment_count"]
    matches = abs(payment_total - (item_total + freight_total)) <= PAYMENT_TOLERANCE_BRL

    # Each check is recorded so the UI can show *why* a rule did or didn't fire.
    checks = [
        {
            "rule": "canceled_order_paid",
            "passed": status == "canceled" and payment_total > 0,
            "detail": f"order_status={status}, payment_total={payment_total}",
        },
        {
            "rule": "unavailable_order_paid",
            "passed": status == "unavailable" and payment_total > 0,
            "detail": f"order_status={status}, payment_total={payment_total}",
        },
        {
            "rule": "late_delivery_seller",
            "passed": late and seller_late,
            "detail": (
                f"delivered_after_estimate={late}, "
                f"carrier_after_shipping_limit={seller_late}"
            ),
        },
        {
            "rule": "late_delivery_logistics",
            "passed": late and not seller_late,
            "detail": (
                f"delivered_after_estimate={late}, "
                f"carrier_after_shipping_limit={seller_late}"
            ),
        },
        {
            "rule": "valid_split_payment",
            "passed": n_payments >= 2 and matches,
            "detail": (
                f"payment_rows={n_payments}, gap={facts['payment_gap_brl']} "
                f"(tolerance {PAYMENT_TOLERANCE_BRL})"
            ),
        },
        {
            "rule": "unsupported_late_claim",
            "passed": (not late) and matches,
            "detail": f"delivered_after_estimate={late}, payment_matches={matches}",
        },
    ]

    passed = {c["rule"]: c["passed"] for c in checks}
    issue = next((r for r in PRIORITY if passed[r]), None)

    if issue is None:
        # Nothing matched (e.g. shipped-but-not-delivered order with a payment
        # mismatch). Fall back to the "no refund owed" branch rather than
        # inventing an issue the policy does not define.
        issue = "unsupported_late_claim"
        fallback = True
    else:
        fallback = False

    cause, party_type, party_id, action, case_status = ISSUE_RULES[issue]

    if issue in ("canceled_order_paid", "unavailable_order_paid"):
        refund = money(payment_total)
    elif issue in ("late_delivery_seller", "late_delivery_logistics"):
        refund = money(freight_total)
    else:
        refund = 0.0

    parties = []
    if party_type == "seller":
        for sid in facts.get("late_seller_ids") or facts.get("seller_ids") or []:
            parties.append({"party_type": "seller", "party_id": sid})
    elif party_type:
        parties.append({"party_type": party_type, "party_id": party_id})

    return {
        "primary_issue": issue,
        "label": ISSUE_LABELS[issue],
        "case_status": case_status,
        "root_cause_code": cause,
        "responsible_parties": parties[:3],
        "recommended_refund_brl": refund,
        "resolution_actions": [action],
        "checks": checks,
        "fallback_applied": fallback,
        "reason": _explain(issue, facts),
    }


def _explain(issue: str, f: dict) -> str:
    """Short Vietnamese rationale, grounded in the numbers we just read."""
    if issue == "canceled_order_paid":
        return (
            f"Đơn ở trạng thái canceled nhưng khách đã thanh toán "
            f"{f['payment_total_brl']} BRL nên phải hoàn toàn bộ."
        )
    if issue == "unavailable_order_paid":
        return (
            f"Đơn ở trạng thái unavailable nhưng đã ghi nhận "
            f"{f['payment_total_brl']} BRL nên phải hoàn toàn bộ."
        )
    if issue == "late_delivery_seller":
        return (
            f"Giao ngày {f['delivered_ts']} trễ hơn hạn {f['estimated_ts']}; "
            f"seller bàn giao cho carrier lúc {f['carrier_ts']} vượt "
            f"shipping_limit_date nên seller chịu trách nhiệm phí vận chuyển "
            f"{f['freight_total_brl']} BRL."
        )
    if issue == "late_delivery_logistics":
        return (
            f"Giao ngày {f['delivered_ts']} trễ hơn hạn {f['estimated_ts']} "
            f"nhưng seller bàn giao đúng hạn ({f['carrier_ts']}), lỗi thuộc đơn vị "
            f"vận chuyển; hoàn freight {f['freight_total_brl']} BRL."
        )
    if issue == "valid_split_payment":
        return (
            f"Đơn có {f['payment_count']} payment row, tổng "
            f"{f['payment_total_brl']} BRL khớp item+freight "
            f"{f['expected_total_brl']} BRL (lệch {f['payment_gap_brl']}), "
            f"không phát sinh hoàn tiền."
        )
    return (
        f"Đơn giao ngày {f['delivered_ts']} không muộn hơn hạn {f['estimated_ts']} "
        f"và thanh toán khớp, khiếu nại giao trễ không có cơ sở."
    )


def build_evidence(facts: dict, resolution: dict) -> list[str]:
    """Evidence IDs, ordered by how much they matter to the decision.

    Works off the ID lists the domain agents handed over ("<order>:<n>" form),
    so the coordinator never has to touch a CSV to cite evidence.
    """
    oid = facts["order_id"]
    issue = resolution["primary_issue"]
    cause = resolution["root_cause_code"]

    item_ids = facts.get("item_ids") or []
    payment_ids = facts.get("payment_ids") or []
    seller_ids = facts.get("seller_ids") or []
    late_sellers = facts.get("late_seller_ids") or []

    def items(n: int) -> list[str]:
        return [f"item:{i}" for i in item_ids[:n]]

    def pays(n: int) -> list[str]:
        return [f"payment:{p}" for p in payment_ids[:n]]

    def sellers(ids: list[str], n: int) -> list[str]:
        return [f"seller:{s}" for s in ids[:n]]

    ev: list[str] = [f"order:{oid}"]
    if issue in ("canceled_order_paid", "unavailable_order_paid"):
        ev += pays(4) + items(2)
    elif issue == "late_delivery_seller":
        prefix = f"{oid}:"
        late_items = [i for i in item_ids if i.startswith(prefix)]
        ev += [f"item:{i}" for i in late_items[:3]]
        ev += sellers(late_sellers or seller_ids, 2) + pays(2)
    elif issue == "late_delivery_logistics":
        ev += items(3) + sellers(seller_ids, 2) + pays(2)
    elif issue == "valid_split_payment":
        ev += pays(4) + items(2)
    else:
        ev += items(2) + pays(2) + sellers(seller_ids, 1)

    ev.append(f"policy:{cause}")

    seen: set[str] = set()
    out: list[str] = []
    for e in ev:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out[:10]
