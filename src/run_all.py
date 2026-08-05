"""Batch runner: every case in input/ -> output/ + trace.jsonl + metadata.json.

    python -m src.run_all                 # all cases, 6 workers
    python -m src.run_all --workers 10    # faster
    python -m src.run_all --only EC_001 EC_007
    python -m src.run_all --limit 5       # smoke run
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .a2a import TraceRecorder
from .config import (
    AGENT_MODELS,
    INPUT_DIR,
    LOG_DIR,
    MODEL_PARAM_BUDGET_B,
    MODEL_PARAM_ESTIMATE_B,
    MODEL_SMALL,
    OUTPUT_DIR,
    POLICY_VERSION,
    ROOT,
    TEMPERATURE,
)
from .datastore import DataStore
from .llm import USAGE
from .pipeline import run_case

if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_cases(only: list[str] | None, limit: int | None) -> list[dict]:
    files = sorted(INPUT_DIR.glob("EC_*.json"))
    if not files:
        raise SystemExit(
            f"no case files in {INPUT_DIR}. Run: python -m src.make_inputs"
        )
    cases = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    if only:
        wanted = set(only)
        cases = [c for c in cases if c["case_id"] in wanted]
    if limit:
        cases = cases[:limit]
    return cases


def write_metadata(stats: dict) -> None:
    meta = {
        "system": "K3 Day-9 Multi-Agent E-commerce Dispute Resolution",
        "version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy_version": POLICY_VERSION,
        "framework": {
            "name": "custom A2A orchestration (no agent framework)",
            "language": f"Python {platform.python_version()}",
            "llm_sdk": "openai-python",
            "libraries": ["pandas", "fastapi", "uvicorn", "pydantic", "python-dotenv"],
            "messaging": "in-process A2A bus, FIPA-style performatives, JSONL trace",
        },
        "models": {
            "provider": "OpenAI",
            "default_model": MODEL_SMALL,
            "per_agent": AGENT_MODELS,
            "parameter_size_estimate_b": MODEL_PARAM_ESTIMATE_B,
            "parameter_budget_b": MODEL_PARAM_BUDGET_B,
            "within_budget": MODEL_PARAM_ESTIMATE_B <= MODEL_PARAM_BUDGET_B,
            "temperature": TEMPERATURE,
            "decoding": "JSON mode (response_format=json_object)",
            "note": (
                "Every agent runs gpt-4o-mini, OpenAI's small tier, publicly "
                "estimated at ~8B active parameters - inside the 10B lab limit."
            ),
        },
        "agents": [
            {"name": "coordinator", "role": "triage, dispatch, assemble", "data_scope": []},
            {"name": "order_seller", "role": "order status, items, sellers, handoff",
             "data_scope": ["orders", "order_items", "sellers", "products"]},
            {"name": "payment", "role": "payment reconciliation",
             "data_scope": ["order_payments", "order_items"]},
            {"name": "delivery", "role": "delivery timeline",
             "data_scope": ["orders", "order_items"]},
            {"name": "policy", "role": "apply EC_POLICY_V1", "data_scope": []},
            {"name": "verifier", "role": "schema/ID/amount verification",
             "data_scope": ["existence checks only"]},
        ],
        "runtime": {
            "os": f"{platform.system()} {platform.release()}",
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "run_stats": stats,
    }
    for path in (ROOT / "metadata.json", LOG_DIR / "metadata.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the agent team over every case")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", type=Path, default=OUTPUT_DIR)
    args = ap.parse_args()

    cases = load_cases(args.only, args.limit)
    args.out.mkdir(parents=True, exist_ok=True)
    USAGE.reset()

    print(f"loading Olist warehouse ...", flush=True)
    store = DataStore()
    print(f"running {len(cases)} cases with {args.workers} workers", flush=True)

    started = time.perf_counter()
    results: dict[str, dict] = {}
    # trace.jsonl at repo root (graded) + logging/trace.jsonl (kept with logs)
    with TraceRecorder(ROOT / "trace.jsonl", LOG_DIR / "trace.jsonl") as rec:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(run_case, case, store, rec): case["case_id"] for case in cases
            }
            done = 0
            for fut in as_completed(futures):
                cid = futures[fut]
                done += 1
                try:
                    res = fut.result()
                except Exception as exc:  # a single bad case must not sink the batch
                    print(f"  [{done}/{len(cases)}] {cid} FAILED: {exc}", flush=True)
                    continue
                results[cid] = res
                out_path = args.out / f"{cid}.json"
                out_path.write_text(
                    json.dumps(res["output"], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                a = res["output"]["assessment"]
                flag = "" if res.get("agreement", True) else "  <- policy disagreement"
                print(
                    f"  [{done}/{len(cases)}] {cid}  {a['primary_issue']:<24}"
                    f" refund={res['output']['financial_resolution']['recommended_refund_brl']:>8.2f}"
                    f"  conf={a['confidence']:.2f}  {res['duration_ms']:.0f}ms{flag}",
                    flush=True,
                )
        rec.write_raw(
            {
                "type": "run_summary",
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "cases": len(results),
                "usage": USAGE.snapshot(),
            }
        )

    wall = round(time.perf_counter() - started, 1)
    issues: dict[str, int] = {}
    refund_total = 0.0
    disagreements = []
    repairs = 0
    divergences = 0
    critical_div = 0
    for cid, res in results.items():
        issues[res["output"]["assessment"]["primary_issue"]] = (
            issues.get(res["output"]["assessment"]["primary_issue"], 0) + 1
        )
        refund_total += res["output"]["financial_resolution"]["recommended_refund_brl"]
        if not res.get("agreement", True):
            disagreements.append(cid)
        repairs += len(res.get("verification", {}).get("repairs", []))
        divergences += len(res.get("divergences", []))
        critical_div += res.get("critical_divergences", 0)

    stats = {
        "cases_run": len(results),
        "wall_seconds": wall,
        "avg_case_seconds": round(wall / max(len(results), 1), 2),
        "issue_distribution": issues,
        "total_recommended_refund_brl": round(refund_total, 2),
        "policy_agreement_rate": round(
            1 - len(disagreements) / max(len(results), 1), 4
        ),
        "policy_disagreement_cases": disagreements,
        "verifier_repairs": repairs,
        "llm_data_divergences": divergences,
        "llm_data_divergences_critical": critical_div,
        "usage": USAGE.snapshot(),
    }
    write_metadata(stats)

    print("\n" + "=" * 68)
    print(f"  {len(results)} cases in {wall}s  ({stats['avg_case_seconds']}s/case)")
    for k, v in sorted(issues.items(), key=lambda kv: -kv[1]):
        print(f"    {k:<26} {v}")
    print(f"  total refund        {stats['total_recommended_refund_brl']:.2f} BRL")
    print(f"  policy agreement    {stats['policy_agreement_rate']*100:.1f}%"
          f"  ({len(disagreements)} disagreement(s))")
    print(f"  verifier repairs    {repairs}")
    print(f"  llm/data divergence {divergences} ({critical_div} critical, caught by guard)")
    u = USAGE.snapshot()
    print(f"  llm calls           {u['calls']}  ({u['total_tokens']} tokens,"
          f" ~${u['estimated_cost_usd']})")
    print(f"  -> output/*.json, trace.jsonl, metadata.json")
    print("=" * 68)


if __name__ == "__main__":
    main()
