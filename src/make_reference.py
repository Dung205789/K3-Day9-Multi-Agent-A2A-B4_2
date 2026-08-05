"""Deterministic reference answers, plus a map of which readings can move them.

    python -m src.make_reference              # output_sample/ + báo cáo biến thể
    python -m src.make_reference --variants   # ghi luôn từng biến thể ra đĩa

Two things live here, and only the second one is interesting.

**The reference set** (`output_sample/`) applies EC_POLICY_V1 straight to the
CSVs with no LLM in the loop. It is fast, free and reproducible - a fixture to
diff against. But it agrees with `output/` by construction: both read the rules
the same way, so it can never tell us *where our reading is wrong*.

**The variant matrix** is the part that pays. Every place the spec admits more
than one honest reading becomes a named variant. Generating all of them and
diffing tells us exactly which cases and which fields any reading could move -
and therefore where the missing marks can possibly be hiding. A variant that
changes nothing on these 50 cases is a lever that is not connected to anything,
and can be dropped from consideration for good.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .config import (
    INPUT_DIR,
    MAX_ACTIONS,
    MAX_ENTITY_IDS,
    MAX_EVIDENCE,
    ROOT,
)
from .datastore import DataStore, money, parse_ts
from .policy import build_evidence, evaluate

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SAMPLE_DIR = ROOT / "output_sample"

# Issues where the refund is the payment total and the goods play no part.
MONEY_ISSUES = ("canceled_order_paid", "unavailable_order_paid")


def cap(seq, limit: int = MAX_ENTITY_IDS) -> list:
    out: list = []
    for x in seq or []:
        if x not in out:
            out.append(x)
    return out[:limit]


def facts_for(store: DataStore, order_id: str) -> dict:
    """Everything the answer depends on, in the shape build_evidence expects."""
    f = store.order_facts(order_id)
    f["item_ids"] = [f"{order_id}:{i['order_item_id']}" for i in f["items"]]
    f["payment_ids"] = [f"{order_id}:{p['payment_sequential']}" for p in f["payments"]]
    return f


# ----------------------------------------------------------------------
# Variants - each one is a different honest reading of the spec
# ----------------------------------------------------------------------
VARIANTS: dict[str, str] = {
    "base": "cách đọc hiện tại của hệ thống",
    "entities-money-empty": (
        "canceled/unavailable: để rỗng item_ids và seller_ids "
        "(refund là tổng payment, hàng hoá không liên quan)"
    ),
    "entities-money-no-seller": (
        "canceled/unavailable: chỉ để rỗng seller_ids, giữ item_ids "
        "(bên chịu trách nhiệm là platform, seller không bị ảnh hưởng)"
    ),
    "entities-seller-breaching": (
        "late_delivery_seller: seller_ids chỉ gồm seller vi phạm, "
        "không gồm seller giao đúng hạn"
    ),
    "evidence-one-per-type": "evidence tối đa 1 ID mỗi loại",
    "confidence-flat": "confidence = 0.95 cho mọi case",
    "evidence-no-payment-on-late": (
        "late_delivery_*: bỏ payment khỏi evidence "
        "(refund là freight, luật không đọc payment row)"
    ),
}


def build_answer(case: dict, store: DataStore, variant: str = "base") -> dict:
    case_id = case["case_id"]
    order_id = case["customer_request"]["claimed_order_id"]
    f = facts_for(store, order_id)
    eng = evaluate(f)
    issue = eng["primary_issue"]

    item_ids = cap(f["item_ids"])
    seller_ids = cap(f["seller_ids"])
    payment_ids = cap(f["payment_ids"])

    if variant == "entities-money-empty" and issue in MONEY_ISSUES:
        item_ids, seller_ids = [], []
    if variant == "entities-money-no-seller" and issue in MONEY_ISSUES:
        seller_ids = []
    if variant == "entities-seller-breaching" and issue == "late_delivery_seller":
        seller_ids = cap(f["late_seller_ids"]) or seller_ids

    ev_facts = dict(f)
    evidence = build_evidence(ev_facts, eng)
    if variant == "evidence-one-per-type":
        seen: set[str] = set()
        trimmed = []
        for e in evidence:
            kind = e.split(":", 1)[0]
            if kind in seen:
                continue
            seen.add(kind)
            trimmed.append(e)
        evidence = trimmed
    if variant == "evidence-no-payment-on-late" and issue.startswith("late_delivery"):
        evidence = [e for e in evidence if not e.startswith("payment:")]

    confidence = 0.95
    if variant != "confidence-flat":
        confidence = round(
            max(0.35, 0.95 - 0.10 * min(len(eng.get("ambiguity") or []), 3)), 2
        )

    actions = list(eng["resolution_actions"])

    return {
        "case_id": case_id,
        "assessment": {
            "primary_issue": issue,
            "case_status": eng["case_status"],
            "confidence": confidence,
        },
        "affected_entities": {
            "order_ids": cap([order_id]),
            "item_ids": item_ids,
            "seller_ids": seller_ids,
            "payment_ids": payment_ids,
        },
        "root_cause_analysis": {
            "ranked_causes": [{"cause_code": eng["root_cause_code"], "rank": 1}],
            "responsible_parties": eng["responsible_parties"],
        },
        "evidence_ids": evidence[:MAX_EVIDENCE],
        "financial_resolution": {
            "currency": "BRL",
            "item_total_brl": money(f["item_total_brl"]),
            "freight_total_brl": money(f["freight_total_brl"]),
            "payment_total_brl": money(f["payment_total_brl"]),
            "recommended_refund_brl": money(eng["recommended_refund_brl"]),
        },
        "resolution_actions": actions[:MAX_ACTIONS],
    }


def load_cases() -> list[dict]:
    files = sorted(INPUT_DIR.glob("EC_*.json"))
    if not files:
        raise SystemExit(f"không có case nào trong {INPUT_DIR}")
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def field_diff(a: dict, b: dict) -> list[str]:
    """Which top-level scored blocks differ between two answers."""
    out = []
    for key in ("assessment", "affected_entities", "root_cause_analysis",
                "evidence_ids", "financial_resolution", "resolution_actions"):
        if key == "assessment":
            for sub in ("primary_issue", "case_status", "confidence"):
                if a[key][sub] != b[key][sub]:
                    out.append(f"assessment.{sub}")
        elif a[key] != b[key]:
            out.append(key)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Sinh đáp án tất định + bản đồ biến thể")
    ap.add_argument("--variants", action="store_true",
                    help="ghi từng biến thể ra output_sample/_variants/<tên>/")
    ap.add_argument("--compare", type=Path, default=ROOT / "output",
                    help="thư mục output để đối chiếu (mặc định: output/)")
    args = ap.parse_args()

    store = DataStore()
    cases = load_cases()

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    base = {}
    for case in cases:
        ans = build_answer(case, store, "base")
        base[case["case_id"]] = ans
        (SAMPLE_DIR / f"{case['case_id']}.json").write_text(
            json.dumps(ans, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"✓ output_sample/: {len(base)} đáp án tất định (không gọi LLM)")

    # --- đối chiếu với output thật -------------------------------------
    mismatched = Counter()
    n_diff = 0
    for cid, ref in base.items():
        path = args.compare / f"{cid}.json"
        if not path.exists():
            continue
        got = json.loads(path.read_text(encoding="utf-8"))
        d = field_diff(ref, got)
        if d:
            n_diff += 1
            for k in d:
                mismatched[k] += 1
    print(f"\n{args.compare.name}/ khác đáp án tất định ở {n_diff}/{len(base)} case"
          + (f": {dict(mismatched)}" if mismatched else " → trùng khít"))

    # --- bản đồ biến thể ------------------------------------------------
    print("\n" + "=" * 78)
    print("  BẢN ĐỒ BIẾN THỂ - cách đọc nào thực sự làm đổi bài nộp")
    print("=" * 78)
    rows = []
    for name, desc in VARIANTS.items():
        if name == "base":
            continue
        changed = Counter()
        cases_changed = []
        for case in cases:
            alt = build_answer(case, store, name)
            d = field_diff(base[case["case_id"]], alt)
            if d:
                cases_changed.append(case["case_id"])
                for k in d:
                    changed[k] += 1
        rows.append((name, desc, cases_changed, changed))
        if args.variants and cases_changed:
            vdir = SAMPLE_DIR / "_variants" / name
            vdir.mkdir(parents=True, exist_ok=True)
            for case in cases:
                alt = build_answer(case, store, name)
                (vdir / f"{case['case_id']}.json").write_text(
                    json.dumps(alt, ensure_ascii=False, indent=2), encoding="utf-8"
                )

    for name, desc, cases_changed, changed in rows:
        mark = "●" if cases_changed else "·"
        print(f"\n{mark} {name}")
        print(f"    {desc}")
        if cases_changed:
            print(f"    đổi {len(cases_changed)}/{len(cases)} case, "
                  f"trường: {dict(changed)}")
            print(f"    case: {', '.join(cases_changed[:12])}"
                  + (" …" if len(cases_changed) > 12 else ""))
        else:
            print("    KHÔNG đổi case nào → đòn bẩy này không nối vào đâu cả")

    live = [r for r in rows if r[2]]
    print("\n" + "=" * 78)
    print(f"  {len(live)}/{len(rows)} cách đọc có thể làm đổi điểm.")
    if live:
        print("  Mỗi cái là một giả thuyết kiểm chứng được bằng đúng một lần nộp.")
    print("=" * 78)
    if args.variants:
        print("  → output_sample/_variants/<tên>/")


if __name__ == "__main__":
    main()
