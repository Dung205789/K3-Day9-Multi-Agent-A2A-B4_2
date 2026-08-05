"""Web backend for the dispute-resolution console.

    python -m src.server        # http://127.0.0.1:8000

Built directly on Starlette rather than FastAPI: this repo's environment ships
starlette 1.3, which FastAPI 0.115 refuses to load ("Router.__init__() got an
unexpected keyword argument 'on_startup'"). Starlette alone covers everything
here - routing, JSON, SSE, static files - with no version pinning to babysit.

Everything the UI shows about a past run is reconstructed from trace.jsonl,
which doubles as proof that the trace really is a complete recording of the
agent conversation. Live re-runs stream the same message objects over SSE.
"""
from __future__ import annotations

import json
import queue
import sys
import threading
from pathlib import Path
from typing import Any, Iterator

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .a2a import Message
from .agents import AGENT_ROLES
from .config import AGENT_MODELS, INPUT_DIR, LOG_DIR, MODEL_SMALL, OUTPUT_DIR, ROOT
from .datastore import AGENT_SCOPES, DataStore
from .pipeline import run_case
from .policy import ISSUE_LABELS, evaluate

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WEB_DIR = ROOT / "web"
TRACE_PATH = ROOT / "trace.jsonl"

_store: DataStore | None = None
_store_lock = threading.Lock()

# Outcome class -> status colour role. Three classes, not six hues: colour
# encodes "what it costs us", the issue name carries the detail.
OUTCOME_CLASS = {
    "canceled_order_paid": "critical",
    "unavailable_order_paid": "critical",
    "late_delivery_seller": "warning",
    "late_delivery_logistics": "warning",
    "valid_split_payment": "good",
    "unsupported_late_claim": "good",
}


def store() -> DataStore:
    global _store
    with _store_lock:
        if _store is None:
            print("loading Olist warehouse ...", flush=True)
            _store = DataStore()
            print("warehouse ready", flush=True)
    return _store


def json_ok(payload: Any) -> JSONResponse:
    return JSONResponse(json.loads(json.dumps(payload, ensure_ascii=False, default=str)))


# ----------------------------------------------------------------------
# Disk readers
# ----------------------------------------------------------------------
def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_inputs() -> dict[str, dict]:
    return {
        f.stem: json.loads(f.read_text(encoding="utf-8"))
        for f in sorted(INPUT_DIR.glob("EC_*.json"))
    }


def load_outputs() -> dict[str, dict]:
    out = {}
    for f in sorted(OUTPUT_DIR.glob("EC_*.json")):
        data = read_json(f)
        if data:
            out[f.stem] = data
    return out


def load_trace() -> dict[str, list[dict]]:
    """Group trace.jsonl by case_id."""
    grouped: dict[str, list[dict]] = {}
    if not TRACE_PATH.exists():
        return grouped
    with TRACE_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            cid = rec.get("case_id")
            if cid:
                grouped.setdefault(cid, []).append(rec)
    return grouped


def digest(messages: list[dict]) -> dict:
    """Pull the interesting payloads out of a case's message list."""
    out: dict[str, Any] = {
        "triage": None, "findings": {}, "policy_verdict": None,
        "verification": None, "summary": None, "disagreement": None,
    }
    for m in messages:
        intent, payload = m.get("intent", ""), m.get("payload", {})
        if intent == "triage":
            out["triage"] = payload
        elif intent.endswith("_findings"):
            out["findings"][m["sender"]] = payload
        elif intent == "policy_verdict":
            out["policy_verdict"] = payload
        elif intent == "verification_report":
            out["verification"] = {k: v for k, v in payload.items() if k != "draft"}
        elif intent == "final_summary":
            out["summary"] = payload
        elif intent == "policy_disagreement":
            out["disagreement"] = payload
    return out


def agent_stats(messages: list[dict]) -> list[dict]:
    """Per-agent latency + token cost for one case."""
    rows: dict[str, dict] = {}
    for m in messages:
        meta = m.get("meta", {})
        if "latency_ms" not in meta:
            continue
        r = rows.setdefault(
            m["sender"], {"agent": m["sender"], "latency_ms": 0.0, "calls": 0,
                          "prompt_tokens": 0, "completion_tokens": 0}
        )
        r["latency_ms"] += meta.get("latency_ms", 0)
        r["calls"] += 1
        r["prompt_tokens"] += meta.get("prompt_tokens", 0) or 0
        r["completion_tokens"] += meta.get("completion_tokens", 0) or 0
    for r in rows.values():
        r["latency_ms"] = round(r["latency_ms"], 1)
    return sorted(rows.values(), key=lambda r: -r["latency_ms"])


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------
async def api_system(request: Request) -> JSONResponse:
    meta = read_json(ROOT / "metadata.json") or {}
    audit = read_json(LOG_DIR / "audit.json") or {}
    return json_ok({
        "metadata": meta,
        "audit": {k: v for k, v in audit.items() if k != "cases_detail"},
        "agents": [
            {
                "name": name,
                "role": AGENT_ROLES.get(name, ""),
                "model": AGENT_MODELS.get(name, MODEL_SMALL),
                "scope": list(AGENT_SCOPES.get(name, ())),
            }
            for name in ("coordinator", "order_seller", "payment", "delivery",
                         "policy", "verifier")
        ],
        "issue_labels": ISSUE_LABELS,
        "outcome_class": OUTCOME_CLASS,
    })


async def api_cases(request: Request) -> JSONResponse:
    inputs, outputs, traces = load_inputs(), load_outputs(), load_trace()
    audit = read_json(LOG_DIR / "audit.json") or {}
    scores = {c["case_id"]: c for c in audit.get("cases_detail", [])}

    rows = []
    for cid, case in inputs.items():
        out = outputs.get(cid)
        msgs = traces.get(cid, [])
        d = digest(msgs) if msgs else {}
        row = {
            "case_id": cid,
            "order_id": case["customer_request"]["claimed_order_id"],
            "message": case["customer_request"]["message"],
            "opened_at": case.get("opened_at"),
            "has_output": out is not None,
            "message_count": len(msgs),
            "agreement": (d.get("disagreement") is None) if msgs else None,
            "score": scores.get(cid, {}).get("score"),
        }
        if out:
            a = out["assessment"]
            fr = out["financial_resolution"]
            row.update({
                "primary_issue": a["primary_issue"],
                "issue_label": ISSUE_LABELS.get(a["primary_issue"], ""),
                "case_status": a["case_status"],
                "confidence": a["confidence"],
                "refund": fr["recommended_refund_brl"],
                "payment_total": fr["payment_total_brl"],
                "outcome_class": OUTCOME_CLASS.get(a["primary_issue"], "good"),
                "action": (out["resolution_actions"] or [None])[0],
            })
        rows.append(row)
    return json_ok({"cases": rows})


async def api_case(request: Request) -> JSONResponse:
    case_id = request.path_params["case_id"]
    inputs = load_inputs()
    if case_id not in inputs:
        return json_ok({"error": f"unknown case {case_id}"})
    case = inputs[case_id]
    order_id = case["customer_request"]["claimed_order_id"]
    msgs = load_trace().get(case_id, [])
    st = store()
    facts = st.order_facts(order_id)
    order = st.order(order_id) or {}
    return json_ok({
        "case_id": case_id,
        "input": case,
        "output": read_json(OUTPUT_DIR / f"{case_id}.json"),
        "transcript": msgs,
        "digest": digest(msgs),
        "agent_stats": agent_stats(msgs),
        "facts": {k: v for k, v in facts.items() if k not in ("items", "payments")},
        "engine": evaluate(facts),
        "raw": {
            "order": order,
            "items": facts.get("items", []),
            "payments": facts.get("payments", []),
            "reviews": st.order_reviews(order_id),
            "sellers": [st.seller(s) for s in facts.get("seller_ids", [])],
            "customer": st.customer(order.get("customer_id", "")),
        },
    })


async def api_run_stream(request: Request) -> StreamingResponse:
    """Re-run one case live; each A2A message is pushed as it happens."""
    case_id = request.path_params["case_id"]
    inputs = load_inputs()
    if case_id not in inputs:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message': 'unknown case'})}\n\n"]),
            media_type="text/event-stream",
        )
    case = inputs[case_id]
    q: "queue.Queue[dict | None]" = queue.Queue()

    def on_message(msg: Message) -> None:
        q.put({"event": "message", "data": msg.to_dict()})

    def worker() -> None:
        try:
            res = run_case(case, store(), on_message=on_message)
            q.put({"event": "done", "data": {
                "output": res["output"],
                "duration_ms": res["duration_ms"],
                "agreement": res.get("agreement"),
                "divergences": res.get("divergences", []),
                "engine": res.get("engine"),
                "summary": res.get("summary"),
                "verification": res.get("verification"),
            }})
        except Exception as exc:
            q.put({"event": "error", "data": {"message": str(exc)}})
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream() -> Iterator[str]:
        yield "retry: 5000\n\n"
        while True:
            item = q.get()
            if item is None:
                break
            payload = json.dumps(item["data"], ensure_ascii=False, default=str)
            yield f"event: {item['event']}\ndata: {payload}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


async def api_order(request: Request) -> JSONResponse:
    order_id = request.path_params["order_id"]
    facts = store().order_facts(order_id)
    if not facts.get("found"):
        return json_ok({"error": f"unknown order {order_id}"})
    return json_ok({"facts": facts, "engine": evaluate(facts)})


async def api_trace_summary(request: Request) -> JSONResponse:
    """Aggregates for the dashboard, computed from the recorded trace."""
    traces = load_trace()
    outputs = load_outputs()
    per_agent: dict[str, dict] = {}
    perf, disagreements, divergence_rows = [], [], []

    for cid, msgs in traces.items():
        for r in agent_stats(msgs):
            acc = per_agent.setdefault(
                r["agent"], {"agent": r["agent"], "latency_ms": 0.0, "calls": 0,
                             "prompt_tokens": 0, "completion_tokens": 0}
            )
            for k in ("latency_ms", "calls", "prompt_tokens", "completion_tokens"):
                acc[k] += r[k]
        perf.append({
            "case_id": cid,
            "llm_ms": round(sum(m.get("meta", {}).get("latency_ms", 0) for m in msgs), 1),
            "messages": len(msgs),
        })
        d = digest(msgs)
        if d.get("disagreement"):
            disagreements.append({"case_id": cid, **d["disagreement"]})
        for m in msgs:
            n = m.get("meta", {}).get("divergences")
            if n:
                divergence_rows.append({"case_id": cid, "agent": m["sender"], "count": n})

    for a in per_agent.values():
        a["latency_ms"] = round(a["latency_ms"], 1)
        a["avg_latency_ms"] = round(a["latency_ms"] / max(a["calls"], 1), 1)

    issues: dict[str, dict] = {}
    confidences = []
    for out in outputs.values():
        issue = out["assessment"]["primary_issue"]
        row = issues.setdefault(issue, {"issue": issue, "count": 0, "refund": 0.0})
        row["count"] += 1
        row["refund"] += out["financial_resolution"]["recommended_refund_brl"]
        confidences.append(out["assessment"]["confidence"])
    for row in issues.values():
        row["refund"] = round(row["refund"], 2)
        row["label"] = ISSUE_LABELS.get(row["issue"], row["issue"])
        row["outcome_class"] = OUTCOME_CLASS.get(row["issue"], "good")

    return json_ok({
        "per_agent": sorted(per_agent.values(), key=lambda r: -r["latency_ms"]),
        "issues": sorted(issues.values(), key=lambda r: -r["count"]),
        "confidences": confidences,
        "case_perf": sorted(perf, key=lambda r: -r["llm_ms"])[:12],
        "disagreements": disagreements,
        "divergences": divergence_rows,
        "total_messages": sum(len(v) for v in traces.values()),
        "cases_traced": len(traces),
    })


async def index(request: Request) -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app = Starlette(routes=[
    Route("/", index),
    Route("/api/system", api_system),
    Route("/api/cases", api_cases),
    Route("/api/case/{case_id}", api_case),
    Route("/api/run/{case_id}/stream", api_run_stream),
    Route("/api/order/{order_id}", api_order),
    Route("/api/trace/summary", api_trace_summary),
    Mount("/static", app=StaticFiles(directory=str(WEB_DIR)), name="static"),
])


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Run the dispute console")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    store()  # warm the warehouse before the first request lands
    print(f"console -> http://{args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
