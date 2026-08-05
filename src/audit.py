"""Self-audit: validate output/ against the schema and against ground truth.

This is *our* scorer, not the official one - but it uses the weights from
README section 8 and recomputes the expected answer straight from the CSVs, so
a case that scores 100 here is one where every field matches what the data says.

    python -m src.audit            # score everything in output/
    python -m src.audit --strict   # exit 1 if any case is below 100
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .config import (
    MAX_ACTIONS,
    MAX_ENTITY_IDS,
    MAX_EVIDENCE,
    MAX_PARTIES,
    MAX_ROOT_CAUSES,
    OUTPUT_DIR,
    PRIMARY_ISSUES,
    RESOLUTION_ACTIONS,
    ROOT,
    ROOT_CAUSE_CODES,
)
from .datastore import DataStore
from .policy import build_evidence, evaluate

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WEIGHTS = {
    "primary_issue": 20,
    "affected_entities": 20,
    "root_cause": 15,
    "evidence": 15,
    "financial": 20,
    "actions": 10,
}

EV_RE = {
    "order": re.compile(r"^order:([^:]+)$"),
    "item": re.compile(r"^item:([^:]+):(\d+)$"),
    "payment": re.compile(r"^payment:([^:]+):(\d+)$"),
    "seller": re.compile(r"^seller:([^:]+)$"),
    "policy": re.compile(r"^policy:([A-Z_]+)$"),
}


def f1(got: list, want: list) -> float:
    g, w = set(map(str, got)), set(map(str, want))
    if not g and not w:
        return 1.0
    if not g or not w:
        return 0.0
    tp = len(g & w)
    if tp == 0:
        return 0.0
    prec, rec = tp / len(g), tp / len(w)
    return 2 * prec * rec / (prec + rec)


def hard_gates(out: dict, store: DataStore) -> list[str]:
    """Failures that would zero the case. Empty list = case is submittable."""
    fails: list[str] = []
    required = [
        "case_id", "assessment", "affected_entities", "root_cause_analysis",
        "evidence_ids", "financial_resolution", "resolution_actions",
    ]
    for key in required:
        if key not in out:
            fails.append(f"missing key: {key}")
    if fails:
        return fails

    a = out["assessment"]
    if a.get("primary_issue") not in PRIMARY_ISSUES:
        fails.append(f"bad primary_issue: {a.get('primary_issue')}")
    if a.get("case_status") not in ("action_required", "no_action"):
        fails.append(f"bad case_status: {a.get('case_status')}")
    c = a.get("confidence")
    if not isinstance(c, (int, float)) or not 0 <= c <= 1:
        fails.append(f"confidence out of range: {c}")

    ae = out["affected_entities"]
    for key in ("order_ids", "item_ids", "seller_ids", "payment_ids"):
        vals = ae.get(key)
        if not isinstance(vals, list):
            fails.append(f"{key} is not a list")
        elif len(vals) > MAX_ENTITY_IDS:
            fails.append(f"{key} exceeds {MAX_ENTITY_IDS}")

    rca = out["root_cause_analysis"]
    causes = rca.get("ranked_causes") or []
    if not causes:
        fails.append("ranked_causes empty")
    if len(causes) > MAX_ROOT_CAUSES:
        fails.append(f"ranked_causes exceeds {MAX_ROOT_CAUSES}")
    for cc in causes:
        if cc.get("cause_code") not in ROOT_CAUSE_CODES:
            fails.append(f"bad cause_code: {cc.get('cause_code')}")
    if len(rca.get("responsible_parties") or []) > MAX_PARTIES:
        fails.append(f"responsible_parties exceeds {MAX_PARTIES}")

    ev = out.get("evidence_ids") or []
    if not ev:
        fails.append("evidence_ids empty")
    if len(ev) > MAX_EVIDENCE:
        fails.append(f"evidence_ids exceeds {MAX_EVIDENCE}")
    for e in ev:
        ok = False
        for kind, rx in EV_RE.items():
            m = rx.match(str(e))
            if not m:
                continue
            ok = m.group(1) in ROOT_CAUSE_CODES if kind == "policy" else store.exists(
                kind, *m.groups()
            )
            break
        if not ok:
            fails.append(f"evidence not reconstructable: {e}")

    fr = out["financial_resolution"]
    if fr.get("currency") != "BRL":
        fails.append("currency must be BRL")
    for key in ("item_total_brl", "freight_total_brl", "payment_total_brl",
                "recommended_refund_brl"):
        if not isinstance(fr.get(key), (int, float)):
            fails.append(f"{key} is not numeric")

    actions = out.get("resolution_actions") or []
    if not actions:
        fails.append("resolution_actions empty")
    if len(actions) > MAX_ACTIONS:
        fails.append(f"resolution_actions exceeds {MAX_ACTIONS}")
    for act in actions:
        if act not in RESOLUTION_ACTIONS:
            fails.append(f"bad action: {act}")
    return fails


def score_case(out: dict, case: dict, store: DataStore) -> dict:
    """Compare one output against ground truth recomputed from the CSVs."""
    order_id = case["customer_request"]["claimed_order_id"]
    facts = store.order_facts(order_id)
    truth = evaluate(facts)
    truth_facts = {
        "order_id": order_id,
        "item_ids": [f"{order_id}:{i['order_item_id']}" for i in facts["items"]],
        "payment_ids": [f"{order_id}:{p['payment_sequential']}" for p in facts["payments"]],
        "seller_ids": facts["seller_ids"],
        "late_seller_ids": facts["late_seller_ids"],
        "late_item_ids": facts["late_item_ids"],
    }
    want_ev = build_evidence(truth_facts, truth)

    parts: dict[str, float] = {}

    issue_ok = out["assessment"]["primary_issue"] == truth["primary_issue"]
    conf = out["assessment"]["confidence"]
    conf_ok = (conf >= 0.7) if issue_ok else (conf < 0.7)
    parts["primary_issue"] = (0.75 * issue_ok + 0.25 * conf_ok) * WEIGHTS["primary_issue"]

    ae = out["affected_entities"]
    ent = (
        f1(ae["order_ids"], [order_id])
        + f1(ae["item_ids"], truth_facts["item_ids"][:MAX_ENTITY_IDS])
        + f1(ae["seller_ids"], facts["seller_ids"][:MAX_ENTITY_IDS])
        + f1(ae["payment_ids"], truth_facts["payment_ids"][:MAX_ENTITY_IDS])
    ) / 4
    parts["affected_entities"] = ent * WEIGHTS["affected_entities"]

    got_causes = [c["cause_code"] for c in out["root_cause_analysis"]["ranked_causes"]]
    cause_ok = bool(got_causes) and got_causes[0] == truth["root_cause_code"]
    got_parties = {
        (p["party_type"], p["party_id"])
        for p in out["root_cause_analysis"]["responsible_parties"]
    }
    want_parties = {(p["party_type"], p["party_id"]) for p in truth["responsible_parties"]}
    party_ok = got_parties == want_parties
    parts["root_cause"] = (0.55 * cause_ok + 0.45 * party_ok) * WEIGHTS["root_cause"]

    parts["evidence"] = f1(out["evidence_ids"], want_ev) * WEIGHTS["evidence"]

    fr = out["financial_resolution"]
    money_hits = sum(
        abs(float(fr[k]) - v) <= 0.01
        for k, v in (
            ("item_total_brl", facts["item_total_brl"]),
            ("freight_total_brl", facts["freight_total_brl"]),
            ("payment_total_brl", facts["payment_total_brl"]),
            ("recommended_refund_brl", truth["recommended_refund_brl"]),
        )
    )
    parts["financial"] = money_hits / 4 * WEIGHTS["financial"]

    parts["actions"] = (
        set(out["resolution_actions"]) == set(truth["resolution_actions"])
    ) * WEIGHTS["actions"]

    gates = hard_gates(out, store)
    total = 0.0 if gates else round(sum(parts.values()), 2)
    return {
        "case_id": out["case_id"],
        "score": total,
        "parts": {k: round(v, 2) for k, v in parts.items()},
        "hard_gate_failures": gates,
        "expected_issue": truth["primary_issue"],
        "got_issue": out["assessment"]["primary_issue"],
        "issue_ok": issue_ok,
        "expected_refund": truth["recommended_refund_brl"],
        "got_refund": fr["recommended_refund_brl"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Self-audit output/ against ground truth")
    ap.add_argument("--out", type=Path, default=OUTPUT_DIR)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    files = sorted(args.out.glob("EC_*.json"))
    if not files:
        raise SystemExit(f"no outputs in {args.out}")

    store = DataStore()
    rows = []
    for f in files:
        out = json.loads(f.read_text(encoding="utf-8"))
        case_path = ROOT / "input" / f.name
        if not case_path.exists():
            print(f"  {f.name}: no matching input, skipped")
            continue
        case = json.loads(case_path.read_text(encoding="utf-8"))
        rows.append(score_case(out, case, store))

    total = sum(r["score"] for r in rows) / max(len(rows), 1)
    gated = [r for r in rows if r["hard_gate_failures"]]
    wrong = [r for r in rows if not r["issue_ok"]]

    print("=" * 74)
    print(f"  SELF-AUDIT  {len(rows)} cases   mean score {total:.2f}/100")
    print("=" * 74)
    for key in WEIGHTS:
        got = sum(r["parts"][key] for r in rows) / max(len(rows), 1)
        print(f"    {key:<20} {got:6.2f} / {WEIGHTS[key]}")
    print(f"    hard-gate failures  {len(gated)}")
    print(f"    wrong primary_issue {len(wrong)}")
    for r in gated[:10]:
        print(f"      {r['case_id']}: {r['hard_gate_failures'][:3]}")
    for r in wrong[:10]:
        print(f"      {r['case_id']}: got {r['got_issue']} want {r['expected_issue']}")

    report = {
        "cases": len(rows),
        "mean_score": round(total, 2),
        "hard_gate_failures": len(gated),
        "wrong_primary_issue": len(wrong),
        "by_component": {
            k: round(sum(r["parts"][k] for r in rows) / max(len(rows), 1), 2)
            for k in WEIGHTS
        },
        "cases_detail": rows,
    }
    (ROOT / "logging" / "audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  -> logging/audit.json")

    if args.strict and (gated or total < 100):
        sys.exit(1)


if __name__ == "__main__":
    main()
