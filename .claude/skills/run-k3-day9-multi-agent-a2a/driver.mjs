#!/usr/bin/env node
/**
 * Driver for the Olist dispute console.
 *
 *   node .claude/skills/run-k3-day9-multi-agent-a2a/driver.mjs smoke
 *   node .claude/skills/run-k3-day9-multi-agent-a2a/driver.mjs run EC_045
 *   node .claude/skills/run-k3-day9-multi-agent-a2a/driver.mjs serve
 *
 * `smoke` boots the server itself, asserts every API endpoint, then drives one
 * real case over SSE and prints the A2A transcript. Exits non-zero on failure,
 * so it works as a check in CI or as a one-command "is this thing alive".
 *
 * Requires the CSVs in data/ and a working OPENAI_API_KEY in .env (the SSE run
 * makes 7 real LLM calls; the API assertions do not).
 */
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const PORT = Number(process.env.PORT || 8765);
const BASE = `http://127.0.0.1:${PORT}`;
const PY = process.env.PYTHON || 'python';

const ok = (s) => `\x1b[32m✓\x1b[0m ${s}`;
const bad = (s) => `\x1b[31m✗\x1b[0m ${s}`;
const dim = (s) => `\x1b[90m${s}\x1b[0m`;

let failures = 0;
function check(label, cond, detail = '') {
  if (cond) console.log(ok(label) + (detail ? ' ' + dim(detail) : ''));
  else { failures += 1; console.log(bad(label) + (detail ? ' ' + detail : '')); }
}

async function getJson(pathname) {
  const res = await fetch(BASE + pathname);
  if (!res.ok) throw new Error(`${pathname} → HTTP ${res.status}`);
  return res.json();
}

/** The warehouse takes ~20s to load; poll until / answers. */
async function waitReady(timeoutMs = 180_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(BASE + '/', { signal: AbortSignal.timeout(4000) });
      if (res.ok) return true;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 1500));
  }
  return false;
}

function startServer() {
  const proc = spawn(PY, ['-m', 'src.server', '--port', String(PORT)], {
    cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });
  proc.stdout.on('data', (b) => process.env.VERBOSE && process.stdout.write(dim(b.toString())));
  proc.stderr.on('data', (b) => process.env.VERBOSE && process.stderr.write(dim(b.toString())));
  return proc;
}

/**
 * Minimal SSE reader. EventSource is not in Node's global scope, and the
 * response body is a byte stream, so events have to be reassembled by hand
 * across chunk boundaries.
 */
async function streamRun(caseId, onEvent) {
  const res = await fetch(`${BASE}/api/run/${caseId}/stream`);
  if (!res.ok) throw new Error(`stream → HTTP ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = 'message';
      const dataLines = [];
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;
      let payload;
      try { payload = JSON.parse(dataLines.join('\n')); } catch { continue; }
      const stop = onEvent(event, payload);
      if (stop) { await reader.cancel(); return; }
    }
  }
}

async function assertApi() {
  const sys = await getJson('/api/system');
  check('GET /api/system', Array.isArray(sys.agents) && sys.agents.length === 6,
    `${sys.agents?.length} agent`);
  const coord = sys.agents.find((a) => a.name === 'coordinator');
  check('coordinator has no data scope', coord && coord.scope.length === 0);
  check('metadata records model', !!sys.metadata?.models?.default_model,
    sys.metadata?.models?.default_model);
  check('model within 10B budget', sys.metadata?.models?.within_budget === true,
    `~${sys.metadata?.models?.parameter_size_estimate_b}B`);

  const { cases } = await getJson('/api/cases');
  check('GET /api/cases', cases.length > 0, `${cases.length} case`);
  const scored = cases.filter((c) => c.has_output);
  check('all cases have output', scored.length === cases.length,
    `${scored.length}/${cases.length}`);

  const first = cases[0].case_id;
  const detail = await getJson(`/api/case/${first}`);
  check(`GET /api/case/${first}`, !!detail.output && detail.transcript.length > 0,
    `${detail.transcript.length} message trong trace`);
  check('raw CSV rows attached', Array.isArray(detail.raw?.items),
    `${detail.raw?.items?.length} item, ${detail.raw?.payments?.length} payment`);
  check('rule engine checks present', detail.engine?.checks?.length === 6);

  const sum = await getJson('/api/trace/summary');
  check('GET /api/trace/summary', sum.total_messages > 0,
    `${sum.total_messages} message, ${sum.cases_traced} case`);

  const html = await (await fetch(BASE + '/')).text();
  check('GET / serves the console', html.includes('Olist Dispute Console'));
  const js = await fetch(BASE + '/static/app.js');
  check('GET /static/app.js', js.ok);
  return cases;
}

async function driveCase(caseId) {
  console.log(`\n${dim('── live run ' + caseId + ' ──')}`);
  const seen = [];
  let done = null;
  const t0 = Date.now();
  await streamRun(caseId, (event, payload) => {
    if (event === 'message') {
      seen.push(payload);
      const ms = String(Math.round(payload.meta?.latency_ms || 0)).padStart(5);
      console.log(
        `  ${String(payload.sender).padStart(13)} → ${String(payload.recipient).padEnd(13)}` +
        ` ${String(payload.performative).padEnd(9)} ${payload.intent} ${dim(ms + 'ms')}`
      );
    } else if (event === 'done') { done = payload; return true; }
    else if (event === 'error') { throw new Error(payload.message); }
    return false;
  });

  const secs = ((Date.now() - t0) / 1000).toFixed(1);
  check('SSE streamed the full conversation', seen.length >= 12, `${seen.length} message, ${secs}s`);
  check('live run produced an output', !!done?.output?.assessment?.primary_issue,
    done?.output?.assessment?.primary_issue);
  check('refund is a number', typeof done?.output?.financial_resolution?.recommended_refund_brl === 'number',
    `${done?.output?.financial_resolution?.recommended_refund_brl} BRL`);
  const senders = new Set(seen.map((m) => m.sender));
  for (const a of ['coordinator', 'order_seller', 'payment', 'delivery', 'policy', 'verifier']) {
    check(`agent ${a} spoke`, senders.has(a));
  }
  const crit = (done?.divergences || []).filter((d) => d.severity === 'critical').length;
  if (crit) console.log(dim(`  ${crit} field lệch giữa LLM và dữ liệu, guard đã ghi đè`));
  return done;
}

// ---------------------------------------------------------------------------
const cmd = process.argv[2] || 'smoke';
const arg = process.argv[3];

if (cmd === 'serve') {
  const proc = startServer();
  console.log(`server đang khởi động trên ${BASE} (Ctrl-C để dừng)`);
  proc.stdout.pipe(process.stdout);
  proc.stderr.pipe(process.stderr);
  process.on('SIGINT', () => { proc.kill(); process.exit(0); });
} else {
  const external = process.env.USE_RUNNING_SERVER === '1';
  const proc = external ? null : startServer();
  let code = 0;
  try {
    console.log(dim(`chờ ${BASE} sẵn sàng (nạp 9 CSV, ~20s) …`));
    if (!(await waitReady())) throw new Error('server không lên trong thời gian chờ');
    console.log(ok('server ready\n'));

    const cases = await assertApi();
    if (cmd === 'run') {
      await driveCase(arg || cases[0].case_id);
    } else if (cmd === 'smoke') {
      await driveCase(arg || cases[0].case_id);
    } else {
      console.log(`lệnh không rõ: ${cmd} (dùng smoke | run <CASE_ID> | serve)`);
      code = 2;
    }
  } catch (err) {
    console.log(bad(String(err.message || err)));
    code = 1;
  } finally {
    proc?.kill();
  }
  console.log(failures ? `\n${bad(failures + ' check thất bại')}` : `\n${ok('tất cả check đạt')}`);
  process.exit(code || (failures ? 1 : 0));
}
