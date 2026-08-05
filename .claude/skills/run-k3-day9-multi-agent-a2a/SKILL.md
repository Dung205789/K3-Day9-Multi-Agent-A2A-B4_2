---
name: run-k3-day9-multi-agent-a2a
description: Build, run, screenshot and drive the K3 Day-9 Olist multi-agent dispute-resolution system - the batch pipeline (50 cases to output/), the self-audit scorer, and the web console with its live SSE agent run. Use when asked to run, start, launch, test, smoke-test, screenshot, or demo this project, or to confirm a change works in the real app rather than in tests.
---

# Run the Olist dispute-resolution system

Two runnable surfaces share one codebase:

- **Batch pipeline** — `python -m src.run_all` runs the agent team over every
  case in `input/` and writes `output/`, `trace.jsonl`, `metadata.json`.
- **Web console** — `python -m src.server` serves a dark operations UI at
  `http://127.0.0.1:8000` that replays `trace.jsonl` and can re-run any case
  live, streaming each A2A message over SSE.

The agent path for both is **`.claude/skills/run-k3-day9-multi-agent-a2a/driver.mjs`**:
it boots the server itself, asserts every endpoint, then drives one real case
over SSE and prints the agent transcript. Start there.

All paths below are relative to the repo root (`D:\VIN_LAB\K3-Day9-Multi-Agent-A2A`).

## Prerequisites

Python 3.12 and Node 20+. Verify the runtime deps:

```bash
python -c "
import sys, importlib
for m in ['pandas','openai','dotenv','starlette','uvicorn']:
    mod = importlib.import_module(m)
    print(f'{m:12}', getattr(mod, '__version__', 'ok'))
print('python      ' + sys.version.split()[0])
"
```

Expected on this machine: pandas 2.3.3, openai 1.109.1, starlette 1.3.1,
uvicorn 0.38.0, python 3.12.4. If anything is missing:

```bash
pip install -r requirements.txt
```

`.env` must hold a real `OPENAI_API_KEY` (see `.env.example`). The model name is
**not** in `.env` — it lives in `src/config.py` (`MODEL_SMALL = "gpt-4o-mini"`).

The nine Olist CSVs must already be in `data/` (they are committed). No build
step: `web/` is three static files, served as-is.

## Run (agent path) — the driver

```bash
node .claude/skills/run-k3-day9-multi-agent-a2a/driver.mjs smoke
```

Boots the server on port 8765, waits for the warehouse to load, asserts
`/api/system`, `/api/cases`, `/api/case/{id}`, `/api/trace/summary`, `/` and
`/static/app.js`, then live-runs the first case and checks that all six agents
spoke. Exits non-zero if any check fails. Takes ~50s (≈20s warehouse load, ≈25s
for the live case's 7 LLM calls).

Drive a specific case — `EC_045` is the one where the policy agent disagrees
with the deterministic rule engine, so it exercises the disagreement path:

```bash
node .claude/skills/run-k3-day9-multi-agent-a2a/driver.mjs run EC_045
```

Prints the full A2A transcript as it streams:

```
       customer → coordinator   request   open_case         0ms
    coordinator → broadcast     inform    triage         5247ms
    coordinator → order_seller  request   investigate       0ms
   order_seller → coordinator   inform    order_seller_findings  2468ms
    coordinator → policy        handoff   apply_policy      0ms
       verifier → coordinator   confirm   verification_report  11346ms
```

Against a server you already started, skip the spawn:

```bash
USE_RUNNING_SERVER=1 PORT=8000 node .claude/skills/run-k3-day9-multi-agent-a2a/driver.mjs smoke
```

`VERBOSE=1` forwards the server's stdout/stderr.

## Run (batch pipeline)

```bash
python -m src.run_all --limit 6 --workers 3     # ~35s, cheap smoke run
python -m src.run_all --workers 8               # all 50, ~95s, ~$0.07
python -m src.run_all --only EC_045             # single case
```

Writes `output/EC_xxx.json`, truncates and rewrites `trace.jsonl` (root **and**
`logging/`), and regenerates `metadata.json`. Prints a per-case line plus a
summary with the issue distribution, policy-agreement rate and token cost.

Then score and package:

```bash
python -m src.audit                # rebuilds ground truth from the CSVs, scores output/
python -m src.package_submission   # output.zip, refuses to build an invalid one
```

`src/audit.py` prints `mean score 100.00/100` and `hard-gate failures 0` on a
healthy run. **Run it after any change to an agent prompt or to `policy.py`** —
it is the fastest signal that a prompt tweak broke accuracy.

Regenerating the inputs (only needed if `input/` is empty):

```bash
python -m src.make_inputs --force
```

## Run (human path) — the console

```bash
python -m src.server               # http://127.0.0.1:8000
python -m src.server --port 8010   # any port
```

Warms the warehouse before binding, so the first request is fast. Three views:
**Hồ sơ** (50 cases; per case: verdict + rule-engine trace, A2A flow, raw CSV
rows, output JSON), **Tổng quan** (charts), **Kiến trúc** (agent graph + scopes).
The "▶ Chạy lại case này" button on the A2A tab re-runs the case for real and
lights up the graph message by message.

To screenshot it, use the Chrome extension tools: `tabs_context_mcp` →
`resize_window` (1600×1000 gives the two-column layout room) → `navigate` to the
URL → `computer` screenshot. **The first screenshot after a navigate usually
fails with "Script injection timed out after 5000ms" — just call it again.**
That error does not mean the page is broken; confirm by checking the server's
access log for `GET /api/cases`.

## Direct invocation (no server, no batch)

Most changes touch one agent or the rule engine. Call them directly:

```bash
python -c "
import json
from src.datastore import DataStore
from src.pipeline import run_case
case = json.load(open('input/EC_002.json', encoding='utf-8'))
r = run_case(case, DataStore())
print(r['output']['assessment'], r['agreement'], r['divergences'])
"
```

The rule engine needs no LLM at all — useful for iterating on `src/policy.py`:

```bash
python -c "
from src.datastore import DataStore
from src.policy import evaluate
s = DataStore()
f = s.order_facts('a56a8219728fdbdc71a20c07b77f1328')
r = evaluate(f)
print(r['primary_issue'], r['recommended_refund_brl'])
for c in r['checks']: print(' ', c['rule'], c['passed'], c['detail'])
"
```

`DataStore()` takes ~20s (it parses ~420k rows). Build it once and reuse it
across cases in any script you write.

## Gotchas

- **A stale `OPENAI_API_KEY` in the shell beats `.env`.** This environment
  exports `OPENAI_API_KEY=your-api-key`, and `load_dotenv()` does not override
  existing env vars, so every agent 401'd with *"Incorrect API key provided:
  your-api-key"*. `src/config.py` now passes `override=True`. If you see that
  exact message, the shell env is winning — the `.env` file is fine.
- **Do not reintroduce FastAPI.** The installed starlette is 1.3.1; FastAPI
  0.115 crashes at import with `Router.__init__() got an unexpected keyword
  argument 'on_startup'`. `src/server.py` is deliberately plain Starlette.
  `requirements.txt` lists starlette + uvicorn only.
- **Windows consoles are cp1252 and the whole UI is Vietnamese.** Every entry
  point calls `sys.stdout.reconfigure(encoding='utf-8')`. Ad-hoc `python -c`
  scripts that print agent output need the same line, or `PYTHONIOENCODING=utf-8`.
- **The verifier's LLM pass is deliberately not allowed to veto.** It used to
  reject every clean draft with boilerplate ("primary_issue không có bằng chứng
  ủng hộ"), which dragged correct cases to confidence 0.62 and cost audit points.
  Two guards in `src/agents/verifier.py`: a `fail` citing under 8 characters of
  evidence is downgraded to `pass`, and a `fail` on a check the deterministic
  pass already proved (`refund_type_correct`, `parties_consistent`) becomes
  `advisory`. If you edit that prompt, re-run `python -m src.audit` — the
  confidence component silently loses points when a *correct* case drops below
  0.7.
- **LLM/data divergences are expected, not a bug.** A clean 50-case run reports
  ~61 divergences (~34 critical). That is the reconcile layer in
  `src/agents/base.py` catching the small model misreading a figure and
  substituting the CSV value. Zero divergences would more likely mean the guard
  stopped running than that the model got perfect.
- **`trace.jsonl` is truncated on every batch run** (the spec wants only the
  latest run). Live runs from the console pass `recorder=None` and never touch
  it, so re-running a case in the UI will not corrupt the submitted trace.
- **The geolocation CSV (1M rows) is not loaded.** `DataStore.load_geolocation()`
  is lazy and nothing in the pipeline calls it. Do not switch it on casually.
- **Payload JSON in the console renders lazily.** An earlier highlighter regex
  with overlapping alternation backtracked catastrophically on the larger
  evidence bundles and froze the tab for minutes. `JSON_TOKEN` in `web/app.js`
  is the linear-time replacement — keep the string branch as `[^"\\]|\\.`.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `LLMError: ... 401 ... Incorrect API key provided: your-api-key` | Shell env var overriding `.env`. Already fixed via `override=True`; if it returns, `unset OPENAI_API_KEY` first. |
| `TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'` | FastAPI/starlette mismatch. `src/server.py` must not import fastapi. |
| `UnicodeEncodeError: 'charmap' codec can't encode character '\u0111'` | cp1252 console. Add `sys.stdout.reconfigure(encoding='utf-8')` or set `PYTHONIOENCODING=utf-8`. |
| `no case files in input/. Run: python -m src.make_inputs` | `input/` is empty; the repo ships it that way. |
| `python -m src.audit` → `no outputs in output/` | Run `python -m src.run_all` first. |
| Console loads but every panel is empty | `trace.jsonl` / `metadata.json` missing — they only exist after a batch run. |
| Screenshot: `Script injection timed out after 5000ms` | Chrome extension race after navigate. Retry the screenshot; check the server access log to confirm the page really loaded. |
| Driver: `server không lên trong thời gian chờ` | Port in use, or the CSV load is still running. Try `PORT=8899`, or `VERBOSE=1` to see the server's own output. |
| `python -m src.package_submission` exits 1 | It lists what is wrong (missing case, stray file, `case_id` not matching the filename). Fix and re-run. |
