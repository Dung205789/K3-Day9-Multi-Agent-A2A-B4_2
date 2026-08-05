"""Entry point: runs every input/EC_*.json case through the multi-agent
pipeline, writes output/EC_*.json and a fresh logging/trace.jsonl.

Usage (from repo root, with .venv activated):
    python src/main.py
    python src/main.py EC_001 EC_002   # run a subset for quick testing
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import policy_rules as pr  # noqa: E402
from agents import coordinator, verifier_agent  # noqa: E402
from schemas import PolicyDecisionDraft  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
TRACE_PATH = ROOT / "logging" / "trace.jsonl"


def _fallback_run(case: dict, error: str) -> tuple[dict, dict]:
    """If the LLM pipeline errors out (rate limit, network...), fall back to
    the deterministic rule engine alone so a valid output is still written."""
    case_id = case["case_id"]
    order_id = case["customer_request"]["claimed_order_id"]
    ground = pr.decide(order_id)
    draft = PolicyDecisionDraft(
        primary_issue=ground.primary_issue,
        cause_code=ground.cause_code,
        confidence=ground.confidence,
        rationale="fallback: deterministic engine only (LLM pipeline error)",
    )
    output, verification = verifier_agent.verify(case_id, order_id, draft)
    trace = {
        "case_id": case_id,
        "order_id": order_id,
        "steps": [{"agent": "fallback_deterministic", "output": verification}],
        "error": error,
    }
    return output.model_dump(), trace


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    TRACE_PATH.parent.mkdir(exist_ok=True)

    only = set(sys.argv[1:])
    case_files = sorted(INPUT_DIR.glob("EC_*.json"))
    if only:
        case_files = [f for f in case_files if f.stem in only]

    traces = []
    ok, failed = 0, 0
    t_start = time.monotonic()

    for idx, path in enumerate(case_files, start=1):
        case = json.loads(path.read_text(encoding="utf-8"))
        case_id = case["case_id"]
        t0 = time.monotonic()
        try:
            output, trace = coordinator.run_case(case)
            output_dict = output.model_dump()
            status = "ok"
            ok += 1
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            print(f"  !! {case_id} pipeline error: {err}", file=sys.stderr)
            traceback.print_exc()
            output_dict, trace = _fallback_run(case, err)
            status = "fallback"
            failed += 1

        (OUTPUT_DIR / path.name).write_text(
            json.dumps(output_dict, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        trace["status"] = status
        trace["total_elapsed_s"] = round(time.monotonic() - t0, 3)
        traces.append(trace)

        elapsed = time.monotonic() - t0
        print(
            f"[{idx}/{len(case_files)}] {case_id} -> "
            f"{output_dict['assessment']['primary_issue']} "
            f"({status}, {elapsed:.1f}s)"
        )

    with TRACE_PATH.open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    total = time.monotonic() - t_start
    print(f"\nDone: {ok} ok, {failed} fallback, {len(case_files)} total, {total:.1f}s")
    print(f"Output written to {OUTPUT_DIR}")
    print(f"Trace written to {TRACE_PATH}")


if __name__ == "__main__":
    main()
