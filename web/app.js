/* Olist Dispute Console.
   No build step, no dependencies - the server serves these three files as-is. */

// ---------------------------------------------------------------------------
// tiny helpers
// ---------------------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const SVG_NS = 'http://www.w3.org/2000/svg';

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

function svg(tag, attrs = {}, ...kids) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

const brl = (n) =>
  Number(n ?? 0).toLocaleString('vi-VN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const int = (n) => Number(n ?? 0).toLocaleString('vi-VN');
const esc = (s) =>
  String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function shortId(id, head = 8) {
  if (!id) return '—';
  return id.length <= head + 4 ? id : `${id.slice(0, head)}…${id.slice(-3)}`;
}

function tsClock(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleTimeString('vi-VN', { hour12: false }) + '.' + String(d.getMilliseconds()).padStart(3, '0');
}

const MAX_JSON_CHARS = 40000;

/* The string branch must be `[^"\\]|\\.` - the two alternatives are mutually
   exclusive, so the star is deterministic. An earlier version used
   `\\u…|\\[^u]|[^\\"]`, whose overlapping branches backtrack catastrophically
   and hung the tab for minutes on the larger evidence-bundle payloads. */
const JSON_TOKEN = /"(?:[^"\\]|\\.)*"(?:\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;

function jsonHighlight(obj) {
  let raw = JSON.stringify(obj, null, 2) ?? '';
  let truncated = false;
  if (raw.length > MAX_JSON_CHARS) {
    raw = raw.slice(0, MAX_JSON_CHARS);
    truncated = true;
  }
  const html = esc(raw).replace(JSON_TOKEN, (m) => {
    let cls = 'n';
    if (m.startsWith('"')) cls = m.endsWith(':') ? 'k' : 's';
    else if (m === 'true' || m === 'false' || m === 'null') cls = 'b';
    return `<span class="${cls}">${m}</span>`;
  });
  return truncated ? html + '\n… (đã cắt bớt)' : html;
}

// tooltip -------------------------------------------------------------------
const tooltip = $('#tooltip');
function showTip(evt, html) {
  tooltip.innerHTML = html;
  tooltip.style.opacity = '1';
  moveTip(evt);
}
function moveTip(evt) {
  const pad = 14;
  const r = tooltip.getBoundingClientRect();
  let x = evt.clientX + pad;
  let y = evt.clientY + pad;
  if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - pad;
  tooltip.style.left = `${x}px`;
  tooltip.style.top = `${y}px`;
}
function hideTip() { tooltip.style.opacity = '0'; }

function bindTip(node, html) {
  node.addEventListener('mouseenter', (e) => showTip(e, html));
  node.addEventListener('mousemove', moveTip);
  node.addEventListener('mouseleave', hideTip);
  return node;
}

// ---------------------------------------------------------------------------
// charts - hand-rolled SVG, thin marks, rounded data-ends, direct labels
// ---------------------------------------------------------------------------
const STATUS_VAR = { good: '--good', warning: '--warning', critical: '--critical', serious: '--serious' };
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const statusColor = (cls) => `var(${STATUS_VAR[cls] || '--series-1'})`;

/** Horizontal bars. `rows` = [{label, value, color, note}] */
function hbarChart(rows, opts = {}) {
  const { valueFmt = int, barH = 18, gap = 12, labelW = 190, valueW = 76, showTrack = true } = opts;
  const H = rows.length * (barH + gap) + 8;
  const width = 760;
  const plotX = labelW;
  const plotW = width - labelW - valueW;
  const max = Math.max(1, ...rows.map((r) => r.value));
  const root = svg('svg', {
    class: 'chart', viewBox: `0 0 ${width} ${H}`, preserveAspectRatio: 'xMinYMin meet',
    role: 'img', 'aria-label': opts.ariaLabel || 'biểu đồ cột ngang',
  });

  rows.forEach((r, i) => {
    const y = i * (barH + gap) + 4;
    const w = Math.max(2, (r.value / max) * plotW);
    const g = svg('g', { class: 'markgroup' });
    g.append(
      svg('text', { class: 'barlabel', x: plotX - 10, y: y + barH * 0.72, 'text-anchor': 'end' }, r.label)
    );
    if (showTrack) {
      g.append(svg('rect', { class: 'track', x: plotX, y, width: plotW, height: barH, rx: 2 }));
    }
    g.append(
      svg('path', { class: 'mark', d: barPath(plotX, y, w, barH, 4), fill: r.color || 'var(--series-1)' })
    );
    g.append(
      svg('text', { class: 'barvalue', x: plotX + plotW + 10, y: y + barH * 0.72 }, valueFmt(r.value))
    );
    bindTip(g, `<div><span class="tt-k">${esc(r.label)}</span></div>
      <div class="tt-v">${valueFmt(r.value)}</div>${r.note ? `<div class="tt-k">${esc(r.note)}</div>` : ''}`);
    root.append(g);
  });
  return root;
}

/** Bar path with only the data-end rounded; baseline end stays square. */
function barPath(x, y, w, h, r) {
  r = Math.min(r, w, h / 2);
  return `M${x},${y} H${x + w - r} A${r},${r} 0 0 1 ${x + w},${y + r} `
       + `V${y + h - r} A${r},${r} 0 0 1 ${x + w - r},${y + h} H${x} Z`;
}

/** Vertical histogram for a distribution of values in [lo, hi]. */
function histogram(values, opts = {}) {
  const { bins = 10, lo = 0, hi = 1, fmt = (v) => v.toFixed(2), color = 'var(--seq-400)' } = opts;
  const counts = new Array(bins).fill(0);
  for (const v of values) {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor(((v - lo) / (hi - lo)) * bins)));
    counts[idx] += 1;
  }
  const width = 760, H = 200, padL = 34, padB = 30, padT = 10, padR = 8;
  const plotW = width - padL - padR, plotH = H - padB - padT;
  const max = Math.max(1, ...counts);
  const root = svg('svg', {
    class: 'chart', viewBox: `0 0 ${width} ${H}`, preserveAspectRatio: 'xMinYMin meet',
    role: 'img', 'aria-label': opts.ariaLabel || 'biểu đồ phân bố',
  });

  for (let t = 0; t <= 4; t++) {
    const v = (max / 4) * t;
    const y = padT + plotH - (v / max) * plotH;
    root.append(svg('line', { class: 'gridline', x1: padL, x2: width - padR, y1: y, y2: y }));
    root.append(svg('text', { class: 'ticklabel', x: padL - 7, y: y + 3, 'text-anchor': 'end' }, Math.round(v)));
  }

  const bw = plotW / bins;
  counts.forEach((c, i) => {
    const h = (c / max) * plotH;
    const x = padL + i * bw;
    const y = padT + plotH - h;
    const g = svg('g', { class: 'markgroup' });
    if (c > 0) {
      g.append(svg('path', { class: 'mark', d: vbarPath(x + 1, y, bw - 2, h, 4), fill: color }));
    }
    const from = lo + (i * (hi - lo)) / bins;
    const to = lo + ((i + 1) * (hi - lo)) / bins;
    bindTip(g, `<div><span class="tt-k">${fmt(from)} – ${fmt(to)}</span></div><div class="tt-v">${c} case</div>`);
    g.append(svg('rect', { x, y: padT, width: bw, height: plotH, fill: 'transparent' }));
    root.append(g);
  });

  root.append(svg('line', { class: 'axisline', x1: padL, x2: width - padR, y1: padT + plotH, y2: padT + plotH }));
  for (let i = 0; i <= bins; i += Math.max(1, Math.round(bins / 5))) {
    const x = padL + i * bw;
    root.append(svg('text', { class: 'ticklabel', x, y: H - 10, 'text-anchor': 'middle' },
      fmt(lo + (i * (hi - lo)) / bins)));
  }
  return root;
}

function vbarPath(x, y, w, h, r) {
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h} V${y + r} A${r},${r} 0 0 1 ${x + r},${y} `
       + `H${x + w - r} A${r},${r} 0 0 1 ${x + w},${y + r} V${y + h} Z`;
}

function legend(items) {
  return el('div', { class: 'legend' },
    items.map((it) =>
      el('span', { class: 'item' },
        el('span', { class: 'sw', style: `background:${it.color}` }),
        it.label)));
}

// ---------------------------------------------------------------------------
// agent graph
// ---------------------------------------------------------------------------
const NODE_POS = {
  customer:     { x: 14,  y: 116, w: 108, h: 44 },
  coordinator:  { x: 168, y: 116, w: 132, h: 44 },
  order_seller: { x: 356, y: 16,  w: 148, h: 48 },
  payment:      { x: 356, y: 114, w: 148, h: 48 },
  delivery:     { x: 356, y: 212, w: 148, h: 48 },
  policy:       { x: 556, y: 114, w: 132, h: 48 },
  verifier:     { x: 736, y: 114, w: 132, h: 48 },
};
const NODE_LABEL = {
  customer: ['customer', 'khiếu nại đầu vào'],
  coordinator: ['coordinator', 'điều phối · tổng hợp'],
  order_seller: ['order_seller', 'đơn · item · seller'],
  payment: ['payment', 'đối soát thanh toán'],
  delivery: ['delivery', 'mốc giao hàng'],
  policy: ['policy', 'EC_POLICY_V1'],
  verifier: ['verifier', 'kiểm chứng đầu ra'],
};
const EDGES = [
  ['customer', 'coordinator'],
  ['coordinator', 'order_seller'],
  ['coordinator', 'payment'],
  ['coordinator', 'delivery'],
  ['coordinator', 'policy'],
  ['policy', 'verifier'],
  ['coordinator', 'verifier'],
];

/* The verifier's scope is the sentinel "__existence__" - it may ask whether an
   ID exists but never read a row, so "1 bảng" would misdescribe it. */
function scopeLabel(scope) {
  if (!scope.length) return 'không truy cập CSDL';
  if (scope[0] === '__existence__') return 'chỉ kiểm tra ID';
  return scope.length + ' bảng';
}
function scopeDetail(scope) {
  if (!scope.length) return 'không có';
  if (scope[0] === '__existence__') return 'chỉ kiểm tra sự tồn tại của ID, không đọc nội dung row';
  return scope.join(', ');
}

function centre(name) {
  const p = NODE_POS[name];
  return p ? { x: p.x + p.w / 2, y: p.y + p.h / 2 } : null;
}

function buildAgentGraph(scopes = {}) {
  const root = svg('svg', {
    class: 'agentgraph', viewBox: '0 0 890 280', preserveAspectRatio: 'xMidYMin meet',
    role: 'img', 'aria-label': 'sơ đồ luồng agent',
  });
  const edgeLayer = svg('g', { class: 'edges' });
  const nodeLayer = svg('g', { class: 'nodes' });

  for (const [a, b] of EDGES) {
    const p = centre(a), q = centre(b);
    const mid = (p.x + q.x) / 2;
    const d = `M${p.x},${p.y} C${mid},${p.y} ${mid},${q.y} ${q.x},${q.y}`;
    edgeLayer.append(svg('path', { class: 'edge', d, 'data-edge': `${a}->${b}` }));
  }

  for (const [name, pos] of Object.entries(NODE_POS)) {
    const [nm, rl] = NODE_LABEL[name];
    const g = svg('g', { class: 'node', 'data-node': name });
    g.append(svg('rect', { x: pos.x, y: pos.y, width: pos.w, height: pos.h }));
    g.append(svg('text', { class: 'nm', x: pos.x + 10, y: pos.y + 18 }, nm));
    g.append(svg('text', { class: 'rl', x: pos.x + 10, y: pos.y + 31 }, rl));
    const scope = scopes[name];
    if (scope !== undefined) {
      g.append(svg('text', { class: 'scope', x: pos.x + 10, y: pos.y + 43 }, scopeLabel(scope)));
      bindTip(g, `<div class="tt-v">${esc(nm)}</div><div class="tt-k">${esc(rl)}</div>
        <div class="tt-k">scope: ${esc(scopeDetail(scope))}</div>`);
    }
    nodeLayer.append(g);
  }

  root.append(edgeLayer, nodeLayer);
  return root;
}

/** Animate one A2A message travelling along its edge. */
function pulseGraph(root, msg) {
  const { sender, recipient } = msg;
  const from = centre(sender), to = centre(recipient);
  $$('.node', root).forEach((n) => n.classList.remove('active'));
  const recvNode = $(`.node[data-node="${recipient}"]`, root);
  const sendNode = $(`.node[data-node="${sender}"]`, root);
  if (sendNode) sendNode.classList.add('done');
  if (recvNode) recvNode.classList.add('active');
  if (!from || !to) return;

  const edge = $(`.edge[data-edge="${sender}->${recipient}"]`, root)
            || $(`.edge[data-edge="${recipient}->${sender}"]`, root);
  if (edge) {
    edge.classList.add('live');
    setTimeout(() => edge.classList.remove('live'), 700);
  }

  const mid = (from.x + to.x) / 2;
  const path = `M${from.x},${from.y} C${mid},${from.y} ${mid},${to.y} ${to.x},${to.y}`;
  const dot = svg('circle', { class: 'pulse', r: 4 });
  const motion = svg('animateMotion', { dur: '0.6s', path, fill: 'freeze', repeatCount: '1' });
  dot.append(motion);
  root.append(dot);
  setTimeout(() => dot.remove(), 700);
}

// ---------------------------------------------------------------------------
// state
// ---------------------------------------------------------------------------
const state = {
  system: null,
  cases: [],
  filters: new Set(),
  search: '',
  selected: null,
  detail: null,
  tab: 'verdict',
  view: 'cases',
  running: false,
  liveGraph: null,
};

const OUTCOME_LABEL = { critical: 'Hoàn toàn bộ', warning: 'Hoàn phí ship', good: 'Không hoàn' };
const OUTCOME_ICON = { critical: '●', warning: '▲', good: '✓' };

async function api(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// case list
// ---------------------------------------------------------------------------
function renderFilters() {
  const box = $('#filters');
  box.innerHTML = '';
  const counts = {};
  for (const c of state.cases) {
    if (!c.primary_issue) continue;
    counts[c.primary_issue] = (counts[c.primary_issue] || 0) + 1;
  }
  const labels = state.system?.issue_labels || {};
  const classes = state.system?.outcome_class || {};
  for (const [issue, n] of Object.entries(counts).sort((a, b) => b[1] - a[1])) {
    const on = state.filters.has(issue);
    box.append(
      el('button', {
        class: 'chip', 'aria-pressed': String(on),
        title: labels[issue] || issue,
        onclick: () => {
          state.filters.has(issue) ? state.filters.delete(issue) : state.filters.add(issue);
          renderFilters(); renderRows();
        },
      },
        el('span', { class: 'dot', style: `background:${statusColor(classes[issue])}` }),
        `${issue.replace(/_/g, ' ')} ${n}`)
    );
  }
}

function visibleCases() {
  const q = state.search.trim().toLowerCase();
  return state.cases.filter((c) => {
    if (state.filters.size && !state.filters.has(c.primary_issue)) return false;
    if (!q) return true;
    return (
      c.case_id.toLowerCase().includes(q) ||
      (c.order_id || '').toLowerCase().includes(q) ||
      (c.message || '').toLowerCase().includes(q) ||
      (c.primary_issue || '').toLowerCase().includes(q)
    );
  });
}

function renderRows() {
  const box = $('#rows');
  box.innerHTML = '';
  const rows = visibleCases();
  if (!rows.length) {
    box.append(el('div', { class: 'empty' }, 'Không có hồ sơ nào khớp bộ lọc.'));
    return;
  }
  for (const c of rows) {
    const cls = c.outcome_class || 'good';
    const row = el('div', {
      class: 'row', 'aria-selected': String(state.selected === c.case_id),
      onclick: () => selectCase(c.case_id),
    },
      el('span', { class: 'bar', style: `background:${statusColor(cls)}` }),
      el('div', { class: 'mid' },
        el('div', { class: 'id' }, c.case_id,
          c.agreement === false ? el('span', { class: 'fired-tag', title: 'Policy agent và rule engine bất đồng' }, 'bất đồng') : null),
        el('div', { class: 'label' }, c.issue_label || c.primary_issue || 'chưa chạy')),
      el('div', { class: 'amt' },
        el('div', {}, c.refund ? brl(c.refund) : '—'),
        el('div', { class: 'c' }, c.confidence != null ? `conf ${c.confidence.toFixed(2)}` : ''))
    );
    box.append(row);
  }
}

// ---------------------------------------------------------------------------
// detail: header
// ---------------------------------------------------------------------------
function renderDetailHead() {
  const head = $('#detailhead');
  head.innerHTML = '';
  const d = state.detail;
  if (!d) {
    head.append(el('div', { class: 'line1' }, el('h2', {}, '—')));
    return;
  }
  const out = d.output;
  const cls = state.system.outcome_class[out?.assessment?.primary_issue] || 'good';
  const req = d.input.customer_request;

  head.append(
    el('div', { class: 'line1' },
      el('h2', {}, d.case_id),
      out ? el('span', { class: `badge ${cls}` },
        el('span', { class: 'dot', style: `background:${statusColor(cls)}` }),
        `${OUTCOME_ICON[cls]} ${OUTCOME_LABEL[cls]}`) : null,
      out ? el('span', { class: 'badge' }, out.assessment.primary_issue) : null,
      out ? el('span', { class: 'badge' }, `refund ${brl(out.financial_resolution.recommended_refund_brl)} BRL`) : null,
      out ? el('span', { class: 'badge' }, `confidence ${out.assessment.confidence.toFixed(2)}`) : null,
      el('span', { class: 'badge mono', title: 'claimed_order_id' }, shortId(req.claimed_order_id, 12)),
      d.digest?.disagreement ? el('span', { class: 'badge critical' },
        el('span', { class: 'dot', style: 'background:var(--critical)' }), 'policy bất đồng') : null),
    el('p', { class: 'claim' }, req.message)
  );
}

// ---------------------------------------------------------------------------
// detail tab: verdict
// ---------------------------------------------------------------------------
function renderVerdict() {
  const pane = $('#pane-verdict');
  pane.innerHTML = '';
  const d = state.detail;
  if (!d?.output) { pane.append(el('div', { class: 'empty' }, 'Case này chưa có output. Chạy pipeline ở tab “Luồng A2A”.')); return; }

  const out = d.output, eng = d.engine, dg = d.digest || {};
  const fr = out.financial_resolution;

  // headline numbers
  pane.append(
    el('div', { class: 'statrow' },
      statCard('Khoản hoàn đề xuất', `${brl(fr.recommended_refund_brl)}`, 'BRL', 'critical-if-nonzero', fr.recommended_refund_brl),
      statCard('Tổng thanh toán', brl(fr.payment_total_brl), 'BRL'),
      statCard('Tiền hàng', brl(fr.item_total_brl), 'BRL'),
      statCard('Phí vận chuyển', brl(fr.freight_total_brl), 'BRL'))
  );

  // narrative from coordinator
  if (dg.summary?.customer_summary) {
    pane.append(
      el('div', { class: 'card' },
        el('h3', {}, 'Tóm tắt gửi khách', el('span', { class: 'tag' }, 'coordinator')),
        el('p', { style: 'margin:0 0 10px;font-size:13.5px' }, dg.summary.customer_summary),
        dg.summary.internal_note
          ? el('p', { style: 'margin:0;font-size:12.5px;color:var(--ink-muted)' }, '▸ Nội bộ: ' + dg.summary.internal_note)
          : null)
    );
  }

  // policy rule trace - the determinism proof
  const checks = el('div', { class: 'checks' });
  for (const c of eng.checks) {
    const fired = c.rule === eng.primary_issue;
    checks.append(
      el('div', { class: `check ${c.passed ? 'pass' : 'fail'} ${fired ? 'fired' : ''}` },
        el('span', { class: 'mark' }, c.passed ? '✓' : '·'),
        el('span', { class: 'rule' }, c.rule,
          fired ? el('span', { class: 'fired-tag' }, 'áp dụng') : null),
        el('span', { class: 'detail' }, c.detail))
    );
  }
  pane.append(
    el('div', { class: 'card' },
      el('h3', {}, 'Rule engine EC_POLICY_V1', el('span', { class: 'tag' }, 'luật đầu tiên khớp sẽ thắng')),
      checks,
      el('p', { style: 'margin:12px 0 0;font-size:13px;color:var(--ink-2)' }, eng.reason))
  );

  // two-column: entities/evidence + policy agent vs engine
  const left = el('div', { class: 'card' },
    el('h3', {}, 'Thực thể và bằng chứng'),
    el('dl', { class: 'kv' },
      el('dt', {}, 'order_ids'), el('dd', {}, pills(out.affected_entities.order_ids, true)),
      el('dt', {}, 'item_ids'), el('dd', {}, pills(out.affected_entities.item_ids, true)),
      el('dt', {}, 'seller_ids'), el('dd', {}, pills(out.affected_entities.seller_ids, true)),
      el('dt', {}, 'payment_ids'), el('dd', {}, pills(out.affected_entities.payment_ids, true))),
    el('h3', { style: 'margin-top:16px' }, `evidence_ids (${out.evidence_ids.length}/10)`),
    el('div', {}, out.evidence_ids.map((e) =>
      el('span', { class: 'pill hit', title: 'ID dựng trực tiếp từ CSV' }, e))));

  const verdictCmp = el('div', { class: 'card' },
    el('h3', {}, 'Hai đường quyết định độc lập'),
    el('table', { class: 'data' },
      el('thead', {}, el('tr', {},
        el('th', {}, ''), el('th', {}, 'Policy agent (LLM)'), el('th', {}, 'Rule engine'))),
      el('tbody', {},
        cmpRow('primary_issue', dg.policy_verdict?.primary_issue, eng.primary_issue),
        cmpRow('root_cause', dg.policy_verdict?.root_cause_code, eng.root_cause_code),
        cmpRow('refund', dg.policy_verdict?.recommended_refund_brl, eng.recommended_refund_brl, brl),
        cmpRow('action', (dg.policy_verdict?.resolution_actions || [])[0], eng.resolution_actions[0]))),
    dg.policy_verdict?.rationale
      ? el('p', { style: 'margin:12px 0 0;font-size:12.5px;color:var(--ink-2)' },
          '▸ Lập luận của policy agent: ' + dg.policy_verdict.rationale)
      : null,
    dg.disagreement
      ? el('p', { style: 'margin:10px 0 0;font-size:12.5px;color:var(--critical)' },
          `▸ Bất đồng: hệ thống lấy kết luận của rule engine (${dg.disagreement.engine_issue}) và ghi lại bất đồng vào trace.`)
      : null);

  pane.append(el('div', { class: 'grid2' }, left, verdictCmp));

  // verifier
  const v = dg.verification;
  if (v) {
    const rows = (v.llm_review?.checks || []).map((c) =>
      el('div', { class: `check ${c.verdict === 'pass' ? 'pass' : 'fail'}` },
        el('span', { class: 'mark' }, c.verdict === 'pass' ? '✓' : c.verdict === 'advisory' ? '!' : '✗'),
        el('span', { class: 'rule' }, c.check),
        el('span', { class: 'detail' }, [c.evidence, c.note].filter(Boolean).join(' — '))));
    pane.append(
      el('div', { class: 'card' },
        el('h3', {}, 'Verifier',
          el('span', { class: 'tag' }, v.approved ? 'thông qua' : 'có cảnh báo')),
        el('div', { class: 'grid2' },
          el('div', {},
            el('div', { style: 'font-size:11px;color:var(--ink-muted);margin-bottom:6px' }, 'KIỂM TRA TẤT ĐỊNH'),
            el('div', { class: 'checks' },
              Object.entries(v.checked || {}).map(([k, ok]) =>
                el('div', { class: `check ${ok ? 'pass' : 'fail'}` },
                  el('span', { class: 'mark' }, ok ? '✓' : '✗'),
                  el('span', { class: 'rule' }, k),
                  el('span', { class: 'detail' }, ok ? 'đạt' : 'không đạt')))),
            v.repairs?.length
              ? el('div', { style: 'margin-top:10px' },
                  el('div', { style: 'font-size:11px;color:var(--warning);margin-bottom:4px' }, `${v.repairs.length} SỬA CHỮA`),
                  v.repairs.map((r) => el('div', { class: 'detail', style: 'font-size:11px;color:var(--ink-2)' }, '· ' + r)))
              : el('div', { style: 'margin-top:10px;font-size:11.5px;color:var(--ink-muted)' }, 'Không phải sửa gì.')),
          el('div', {},
            el('div', { style: 'font-size:11px;color:var(--ink-muted);margin-bottom:6px' }, 'RÀ SOÁT BẰNG LLM'),
            el('div', { class: 'checks' }, rows.length ? rows : el('div', { class: 'detail' }, '—')),
            v.llm_review?.review
              ? el('p', { style: 'margin:10px 0 0;font-size:12px;color:var(--ink-2)' }, v.llm_review.review)
              : null)))
    );
  }
}

function statCard(k, v, unit, mode, raw) {
  const danger = mode === 'critical-if-nonzero' && Number(raw) > 0;
  return el('div', { class: 'card' },
    el('div', { class: 'stat' },
      el('span', { class: 'v', style: danger ? 'color:var(--critical)' : '' }, v,
        unit ? el('span', { style: 'font-size:13px;color:var(--ink-muted);font-weight:500' }, ' ' + unit) : null),
      el('span', { class: 'k' }, k)));
}

function pills(list, mono) {
  if (!list?.length) return el('span', { style: 'color:var(--ink-muted)' }, '(rỗng)');
  return el('span', {}, list.map((x) => el('span', { class: 'pill', title: x }, mono ? shortId(x, 10) : x)));
}

function cmpRow(label, a, b, fmt = (x) => String(x ?? '—')) {
  const same = String(a ?? '') === String(b ?? '') ||
    (typeof a === 'number' && Math.abs(Number(a) - Number(b)) < 0.005);
  return el('tr', {},
    el('td', { style: 'color:var(--ink-muted)' }, label),
    el('td', { class: 'mono', style: same ? '' : 'color:var(--critical)' }, fmt(a)),
    el('td', { class: 'mono' }, fmt(b),
      same ? null : el('span', { class: 'fired-tag', style: 'background:var(--critical)' }, 'dùng cái này')));
}

// ---------------------------------------------------------------------------
// detail tab: A2A flow (+ live run)
// ---------------------------------------------------------------------------
function renderFlow() {
  const pane = $('#pane-flow');
  pane.innerHTML = '';
  const d = state.detail;
  if (!d) return;

  const scopes = Object.fromEntries((state.system.agents || []).map((a) => [a.name, a.scope]));
  const graph = buildAgentGraph(scopes);
  state.liveGraph = graph;

  const runBtn = el('button', { class: 'btn-run', onclick: () => runLive(d.case_id) }, '▶ Chạy lại case này');
  const status = el('span', { class: 'runstatus', id: 'runstatus' },
    `${d.transcript.length} message đã ghi trong trace.jsonl`);

  pane.append(
    el('div', { class: 'runbar' }, runBtn, status,
      el('span', { style: 'font-size:11.5px;color:var(--ink-muted)' },
        'Mỗi lần chạy gọi thật 7 lượt LLM, ~10–15 giây.')),
    el('div', { class: 'card graphwrap' },
      el('h3', {}, 'Sơ đồ handoff', el('span', { class: 'tag' }, 'node sáng lên khi nhận message')),
      graph),
    el('div', { class: 'card' },
      el('h3', {}, 'Transcript A2A', el('span', { class: 'tag', id: 'msgcount' }, `${d.transcript.length} message`)),
      el('div', { class: 'transcript', id: 'transcript' },
        d.transcript.map((m) => messageRow(m))))
  );

  // agent cost table
  if (d.agent_stats?.length) {
    pane.append(
      el('div', { class: 'card' },
        el('h3', {}, 'Chi phí theo agent', el('span', { class: 'tag' }, 'lượt chạy đã ghi')),
        el('div', { class: 'scrollx' },
          el('table', { class: 'data' },
            el('thead', {}, el('tr', {},
              el('th', {}, 'agent'), el('th', {}, 'lượt gọi'), el('th', {}, 'latency (ms)'),
              el('th', {}, 'prompt tok'), el('th', {}, 'completion tok'))),
            el('tbody', {}, d.agent_stats.map((r) =>
              el('tr', {},
                el('td', { class: 'mono' }, r.agent),
                el('td', {}, r.calls),
                el('td', {}, int(Math.round(r.latency_ms))),
                el('td', {}, int(r.prompt_tokens)),
                el('td', {}, int(r.completion_tokens))))))))
    );
  }
}

function messageRow(m, isNew = false) {
  const meta = m.meta || {};
  const bits = [];
  if (meta.latency_ms) bits.push(`${Math.round(meta.latency_ms)}ms`);
  if (meta.prompt_tokens) bits.push(`${meta.prompt_tokens}+${meta.completion_tokens} tok`);
  if (meta.tables_read?.length) bits.push(meta.tables_read.join('·'));
  if (meta.divergences) bits.push(`${meta.divergences} lệch`);

  return el('div', { class: `msg ${isNew ? 'new' : ''}` },
    el('div', { class: 't' }, tsClock(m.ts)),
    el('div', { class: 'body' },
      el('div', { class: 'hdr' },
        el('span', { class: 'from' }, m.sender),
        el('span', { class: 'arrow' }, '→'),
        el('span', { class: 'to' }, m.recipient),
        el('span', { class: `perf ${m.performative}` }, m.performative),
        el('span', { class: 'intent' }, m.intent),
        bits.length ? el('span', { class: 'meta' }, bits.join(' · ')) : null),
      lazyJson('payload', m.payload)));
}

/** Highlight only when the reader actually opens the block. */
function lazyJson(label, obj) {
  const pre = el('pre', { class: 'json' }, '…');
  const box = el('details', { class: 'payload' }, el('summary', {}, label), pre);
  box.addEventListener('toggle', () => {
    if (box.open && !box.dataset.rendered) {
      box.dataset.rendered = '1';
      pre.innerHTML = jsonHighlight(obj);
    }
  });
  return box;
}

function runLive(caseId) {
  if (state.running) return;
  state.running = true;
  const btn = $('.btn-run');
  const status = $('#runstatus');
  const list = $('#transcript');
  if (btn) { btn.disabled = true; btn.textContent = '⋯ đang chạy'; }
  list.innerHTML = '';
  $$('.node', state.liveGraph).forEach((n) => n.classList.remove('active', 'done'));

  let count = 0;
  const t0 = performance.now();
  const src = new EventSource(`/api/run/${caseId}/stream`);

  src.addEventListener('message', (evt) => {
    const m = JSON.parse(evt.data);
    count += 1;
    if (state.liveGraph) pulseGraph(state.liveGraph, m);
    list.append(messageRow(m, true));
    list.lastChild.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    $('#msgcount').textContent = `${count} message`;
    status.textContent = `${count} message · ${((performance.now() - t0) / 1000).toFixed(1)}s · ${m.sender} → ${m.recipient}`;
  });

  src.addEventListener('done', (evt) => {
    const res = JSON.parse(evt.data);
    src.close();
    state.running = false;
    if (btn) { btn.disabled = false; btn.textContent = '▶ Chạy lại case này'; }
    $$('.node', state.liveGraph).forEach((n) => n.classList.remove('active'));
    const crit = (res.divergences || []).filter((d) => d.severity === 'critical').length;
    status.innerHTML = `<span style="color:var(--good)">✓ xong</span> · ${count} message · `
      + `${(res.duration_ms / 1000).toFixed(1)}s · kết luận <b>${esc(res.output.assessment.primary_issue)}</b> · `
      + `hoàn ${brl(res.output.financial_resolution.recommended_refund_brl)} BRL`
      + (crit ? ` · <span style="color:var(--warning)">${crit} lệch LLM/dữ liệu đã chặn</span>` : '');

    if (res.divergences?.length) {
      const box = el('div', { class: 'card' },
        el('h3', {}, 'LLM nói khác dữ liệu', el('span', { class: 'tag' }, 'guard đã ghi đè bằng giá trị thật')),
        el('div', { class: 'scrollx' },
          el('table', { class: 'data' },
            el('thead', {}, el('tr', {},
              el('th', {}, 'agent'), el('th', {}, 'field'), el('th', {}, 'LLM'), el('th', {}, 'dữ liệu'), el('th', {}, 'mức'))),
            el('tbody', {}, res.divergences.map((dv) =>
              el('tr', {},
                el('td', { class: 'mono' }, dv.agent),
                el('td', { class: 'mono' }, dv.field),
                el('td', { class: 'mono', style: 'color:var(--critical)' }, JSON.stringify(dv.llm)),
                el('td', { class: 'mono', style: 'color:var(--good)' }, JSON.stringify(dv.data)),
                el('td', {}, dv.severity)))))));
      $('#pane-flow').append(box);
      box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    loadCases();
  });

  src.addEventListener('error', () => {
    src.close();
    state.running = false;
    if (btn) { btn.disabled = false; btn.textContent = '▶ Chạy lại case này'; }
    status.innerHTML = '<span style="color:var(--critical)">✗ mất kết nối stream</span>';
  });
}

// ---------------------------------------------------------------------------
// detail tab: raw data
// ---------------------------------------------------------------------------
function renderData() {
  const pane = $('#pane-data');
  pane.innerHTML = '';
  const d = state.detail;
  if (!d) return;
  const raw = d.raw, f = d.facts;

  pane.append(
    el('div', { class: 'card' },
      el('h3', {}, 'Mốc thời gian đơn hàng', el('span', { class: 'tag' }, 'olist_orders_dataset.csv')),
      timeline(f))
  );

  pane.append(
    el('div', { class: 'card' },
      el('h3', {}, `order_items (${raw.items.length})`, el('span', { class: 'tag' }, 'olist_order_items_dataset.csv')),
      el('div', { class: 'scrollx' },
        el('table', { class: 'data' },
          el('thead', {}, el('tr', {},
            el('th', {}, '#'), el('th', {}, 'seller_id'), el('th', {}, 'shipping_limit_date'),
            el('th', {}, 'price'), el('th', {}, 'freight'), el('th', {}, 'bàn giao'))),
          el('tbody', {}, raw.items.map((it) => {
            const late = (f.late_seller_ids || []).includes(it.seller_id);
            return el('tr', {},
              el('td', { class: 'mono' }, it.order_item_id),
              el('td', { class: 'mono', title: it.seller_id }, shortId(it.seller_id, 10)),
              el('td', { class: 'mono' }, it.shipping_limit_date),
              el('td', {}, brl(it.price)),
              el('td', {}, brl(it.freight_value)),
              el('td', { style: late ? 'color:var(--warning)' : 'color:var(--good)' },
                late ? '▲ trễ hạn' : '✓ đúng hạn'));
          })))))
  );

  pane.append(
    el('div', { class: 'card' },
      el('h3', {}, `order_payments (${raw.payments.length})`, el('span', { class: 'tag' }, 'olist_order_payments_dataset.csv')),
      el('div', { class: 'scrollx' },
        el('table', { class: 'data' },
          el('thead', {}, el('tr', {},
            el('th', {}, 'seq'), el('th', {}, 'type'), el('th', {}, 'installments'), el('th', {}, 'value'))),
          el('tbody', {}, raw.payments.map((p) =>
            el('tr', {},
              el('td', { class: 'mono' }, p.payment_sequential),
              el('td', {}, p.payment_type),
              el('td', {}, p.payment_installments),
              el('td', {}, brl(p.payment_value))))))),
      el('dl', { class: 'kv', style: 'margin-top:12px' },
        el('dt', {}, 'tổng payment'), el('dd', {}, brl(f.payment_total_brl) + ' BRL'),
        el('dt', {}, 'item + freight'), el('dd', {}, brl(f.expected_total_brl) + ' BRL'),
        el('dt', {}, 'chênh lệch'), el('dd', { style: f.payment_matches ? 'color:var(--good)' : 'color:var(--critical)' },
          `${brl(f.payment_gap_brl)} BRL — ${f.payment_matches ? 'khớp (≤0.10)' : 'không khớp'}`)))
  );

  const seller = (raw.sellers || []).filter(Boolean);
  pane.append(
    el('div', { class: 'grid2' },
      el('div', { class: 'card' },
        el('h3', {}, 'Khách hàng', el('span', { class: 'tag' }, 'olist_customers_dataset.csv')),
        raw.customer
          ? el('dl', { class: 'kv' },
              el('dt', {}, 'customer_id'), el('dd', { class: 'mono' }, shortId(raw.customer.customer_id, 14)),
              el('dt', {}, 'unique_id'), el('dd', { class: 'mono' }, shortId(raw.customer.customer_unique_id, 14)),
              el('dt', {}, 'thành phố'), el('dd', {}, `${raw.customer.customer_city}, ${raw.customer.customer_state}`),
              el('dt', {}, 'zip'), el('dd', { class: 'mono' }, raw.customer.customer_zip_code_prefix))
          : el('div', { class: 'empty' }, 'không có')),
      el('div', { class: 'card' },
        el('h3', {}, `Seller (${seller.length})`, el('span', { class: 'tag' }, 'olist_sellers_dataset.csv')),
        seller.length
          ? el('table', { class: 'data' },
              el('thead', {}, el('tr', {}, el('th', {}, 'seller_id'), el('th', {}, 'thành phố'), el('th', {}, 'bang'))),
              el('tbody', {}, seller.map((s) =>
                el('tr', {},
                  el('td', { class: 'mono', title: s.seller_id }, shortId(s.seller_id, 10)),
                  el('td', {}, s.seller_city),
                  el('td', {}, s.seller_state)))))
          : el('div', { class: 'empty' }, 'không có')))
  );

  if (raw.reviews?.length) {
    pane.append(
      el('div', { class: 'card' },
        el('h3', {}, 'Đánh giá của khách', el('span', { class: 'tag' }, 'olist_order_reviews_dataset.csv — không dùng cho quyết định')),
        raw.reviews.map((r) =>
          el('div', { style: 'margin-bottom:10px' },
            el('div', { style: 'font-size:12px;color:var(--ink-muted)' },
              `${'★'.repeat(Number(r.review_score))}${'☆'.repeat(5 - Number(r.review_score))}  ${r.review_creation_date}`),
            r.review_comment_message
              ? el('div', { style: 'font-size:12.5px;color:var(--ink-2)' }, r.review_comment_message)
              : null)))
    );
  }
}

function timeline(f) {
  const points = [
    ['đặt hàng', f.purchase_ts],
    ['duyệt', f.approved_ts],
    ['giao carrier', f.carrier_ts],
    ['giao khách', f.delivered_ts],
    ['hạn cam kết', f.estimated_ts],
  ].filter(([, v]) => v);
  const times = points.map(([, v]) => new Date(v.replace(' ', 'T')).getTime());
  const lo = Math.min(...times), hi = Math.max(...times);
  const span = Math.max(1, hi - lo);
  const W = 760, H = 132, axisY = 66, padL = 46, padR = 46;
  const plotW = W - padL - padR;
  const root = svg('svg', { class: 'chart', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'mốc thời gian đơn hàng' });
  root.append(svg('line', { class: 'axisline', x1: padL, x2: W - padR, y1: axisY, y2: axisY }));

  /* Real orders bunch several events into the same hour, so fixed above/below
     alternation piled labels on top of each other. Place each label in the
     first lane whose previous label has cleared, alternating sides first. */
  const LANES = [
    { y: axisY - 18, dy: -12 },   // just above
    { y: axisY + 26, dy: 12 },    // just below
    { y: axisY - 44, dy: -12 },   // second row above
    { y: axisY + 52, dy: 12 },    // second row below
  ];
  const laneEnd = LANES.map(() => -Infinity);

  const placed = points
    .map(([label, value]) => ({
      label, value,
      x: padL + ((new Date(value.replace(' ', 'T')).getTime() - lo) / span) * plotW,
    }))
    .sort((a, b) => a.x - b.x);

  for (const p of placed) {
    const halfW = Math.max(String(p.label).length, 10) * 3.1;
    let lane = LANES.findIndex((_, i) => p.x - halfW > laneEnd[i] + 6);
    if (lane === -1) lane = LANES.length - 1;
    laneEnd[lane] = p.x + halfW;

    // Keep edge labels inside the frame instead of letting them clip.
    let anchor = 'middle';
    if (p.x - halfW < 2) anchor = 'start';
    else if (p.x + halfW > W - 2) anchor = 'end';
    const tx = anchor === 'start' ? Math.max(p.x - halfW, 2)
             : anchor === 'end' ? Math.min(p.x + halfW, W - 2) : p.x;

    const isEstimate = p.label === 'hạn cam kết';
    const late = isEstimate && f.delivered_after_estimate;
    const color = isEstimate ? (late ? 'var(--critical)' : 'var(--good)') : 'var(--seq-400)';
    const { y, dy } = LANES[lane];
    const g = svg('g', { class: 'markgroup' });
    g.append(svg('line', {
      x1: p.x, x2: p.x, y1: Math.min(axisY, y + (dy < 0 ? 4 : -4)),
      y2: Math.max(axisY, y + (dy < 0 ? 4 : -4)),
      stroke: color, 'stroke-width': 1, opacity: 0.5,
    }));
    g.append(svg('circle', { cx: p.x, cy: axisY, r: 4.5, fill: color, stroke: 'var(--surface-1)', 'stroke-width': 2 }));
    g.append(svg('text', {
      class: 'ticklabel', x: tx, y, 'text-anchor': anchor,
      style: 'fill:var(--ink-2);font-size:10.5px',
    }, p.label));
    g.append(svg('text', {
      class: 'ticklabel', x: tx, y: y + dy, 'text-anchor': anchor,
    }, p.value.slice(0, 10)));
    bindTip(g, `<div class="tt-v">${esc(p.label)}</div><div class="tt-k">${esc(p.value)}</div>`);
    root.append(g);
  }

  const wrap = el('div', {}, root);
  if (f.delivery_delay_days != null) {
    const late = f.delivered_after_estimate;
    wrap.append(el('p', { style: `margin:8px 0 0;font-size:12.5px;color:${late ? 'var(--critical)' : 'var(--good)'}` },
      late
        ? `▲ Giao trễ ${Math.abs(f.delivery_delay_days).toFixed(1)} ngày so với hạn cam kết.`
        : `✓ Giao sớm hơn hạn ${Math.abs(f.delivery_delay_days).toFixed(1)} ngày.`));
  }
  return wrap;
}

// ---------------------------------------------------------------------------
// detail tab: json
// ---------------------------------------------------------------------------
function renderJson() {
  const pane = $('#pane-json');
  pane.innerHTML = '';
  const d = state.detail;
  if (!d) return;
  pane.append(
    el('div', { class: 'grid2' },
      el('div', { class: 'card' },
        el('h3', {}, `input/${d.case_id}.json`),
        el('pre', { class: 'json', html: jsonHighlight(d.input) })),
      el('div', { class: 'card' },
        el('h3', {}, `output/${d.case_id}.json`,
          el('span', { class: 'tag' }, 'file nộp bài')),
        d.output
          ? el('pre', { class: 'json', html: jsonHighlight(d.output) })
          : el('div', { class: 'empty' }, 'chưa có output')))
  );
}

// ---------------------------------------------------------------------------
// overview
// ---------------------------------------------------------------------------
async function renderOverview() {
  const body = $('#overviewBody');
  body.innerHTML = '<div class="empty">đang tải…</div>';
  const [sum, sys] = await Promise.all([api('/api/trace/summary'), api('/api/system')]);
  const audit = sys.audit || {};
  const stats = sys.metadata?.run_stats || {};
  const usage = stats.usage || {};
  body.innerHTML = '';

  body.append(
    el('div', { class: 'statrow' },
      statCard('Case đã xử lý', int(stats.cases_run ?? sum.cases_traced)),
      statCard('Self-audit', (audit.mean_score ?? 0).toFixed(2), '/100'),
      statCard('Hard-gate lỗi', int(audit.hard_gate_failures ?? 0)),
      statCard('Tổng hoàn đề xuất', brl(stats.total_recommended_refund_brl), 'BRL'),
      statCard('Message A2A', int(sum.total_messages)),
      statCard('Chi phí LLM', '$' + (usage.estimated_cost_usd ?? 0).toFixed(4)))
  );

  // issue distribution + refund
  const issues = sum.issues || [];
  body.append(
    el('div', { class: 'grid2' },
      el('div', { class: 'card' },
        el('h3', {}, 'Phân bố kết luận', el('span', { class: 'tag' }, `${issues.reduce((a, b) => a + b.count, 0)} case`)),
        hbarChart(issues.map((r) => ({
          label: r.issue, value: r.count, color: statusColor(r.outcome_class), note: r.label,
        })), { labelW: 210, valueW: 44, ariaLabel: 'số case theo primary issue' }),
        legend([
          { label: 'Hoàn toàn bộ tiền', color: 'var(--critical)' },
          { label: 'Hoàn phí vận chuyển', color: 'var(--warning)' },
          { label: 'Không hoàn tiền', color: 'var(--good)' },
        ])),
      el('div', { class: 'card' },
        el('h3', {}, 'Số tiền hoàn theo nhóm', el('span', { class: 'tag' }, 'BRL')),
        hbarChart(issues.filter((r) => r.refund > 0).map((r) => ({
          label: r.issue, value: r.refund, color: statusColor(r.outcome_class), note: `${r.count} case`,
        })), { labelW: 210, valueW: 84, valueFmt: brl, ariaLabel: 'tổng hoàn theo primary issue' })))
  );

  // confidence + agent cost
  body.append(
    el('div', { class: 'grid2' },
      el('div', { class: 'card' },
        el('h3', {}, 'Phân bố confidence', el('span', { class: 'tag' }, 'điểm tự tin của hệ thống')),
        histogram(sum.confidences || [], {
          bins: 10, lo: 0.5, hi: 1.0, fmt: (v) => v.toFixed(2), ariaLabel: 'phân bố confidence',
        })),
      el('div', { class: 'card' },
        el('h3', {}, 'Thời gian LLM theo agent', el('span', { class: 'tag' }, 'tổng ms toàn bộ run')),
        hbarChart((sum.per_agent || []).map((r) => ({
          label: r.agent, value: Math.round(r.latency_ms),
          color: 'var(--seq-400)', note: `${r.calls} lượt · ${r.avg_latency_ms}ms/lượt`,
        })), { labelW: 130, valueW: 76, ariaLabel: 'độ trễ theo agent' })))
  );

  // quality panel
  const div = sum.divergences || [];
  const byAgent = {};
  for (const d of div) byAgent[d.agent] = (byAgent[d.agent] || 0) + d.count;
  body.append(
    el('div', { class: 'grid2' },
      el('div', { class: 'card' },
        el('h3', {}, 'Guard chặn được gì', el('span', { class: 'tag' }, 'LLM khác dữ liệu')),
        Object.keys(byAgent).length
          ? hbarChart(Object.entries(byAgent).sort((a, b) => b[1] - a[1]).map(([a, n]) => ({
              label: a, value: n, color: 'var(--warning)', note: 'số field bị ghi đè bằng giá trị thật',
            })), { labelW: 130, valueW: 44, ariaLabel: 'số lần LLM lệch dữ liệu theo agent' })
          : el('div', { class: 'empty' }, 'không có sai lệch nào'),
        el('p', { style: 'margin:10px 0 0;font-size:12px;color:var(--ink-2)' },
          `Tổng ${stats.llm_data_divergences ?? div.reduce((a, b) => a + b.count, 0)} field bị LLM đọc sai `
          + `(${stats.llm_data_divergences_critical ?? '—'} ảnh hưởng tới nhánh policy) — tất cả đã bị lớp `
          + `reconcile ghi đè bằng giá trị tính từ CSV.`)),
      el('div', { class: 'card' },
        el('h3', {}, 'Bất đồng policy agent vs rule engine',
          el('span', { class: 'tag' }, `${(sum.disagreements || []).length} case`)),
        (sum.disagreements || []).length
          ? el('table', { class: 'data' },
              el('thead', {}, el('tr', {},
                el('th', {}, 'case'), el('th', {}, 'LLM kết luận'), el('th', {}, 'engine kết luận'))),
              el('tbody', {}, sum.disagreements.map((d) =>
                el('tr', {},
                  el('td', { class: 'mono clickable', style: 'cursor:pointer;color:var(--seq-250)',
                    onclick: () => { switchView('cases'); selectCase(d.case_id); } }, d.case_id),
                  el('td', { class: 'mono', style: 'color:var(--critical)' }, d.llm_issue),
                  el('td', { class: 'mono', style: 'color:var(--good)' }, d.engine_issue)))))
          : el('div', { class: 'empty' }, 'không có bất đồng'),
        el('p', { style: 'margin:10px 0 0;font-size:12px;color:var(--ink-2)' },
          'Khi hai đường quyết định lệch nhau, hệ thống lấy rule engine và hạ confidence của case đó.')))
  );

  // component scores
  if (audit.by_component) {
    const weights = { primary_issue: 20, affected_entities: 20, root_cause: 15, evidence: 15, financial: 20, actions: 10 };
    body.append(
      el('div', { class: 'card' },
        el('h3', {}, 'Tự chấm theo trọng số đề bài', el('span', { class: 'tag' }, 'logging/audit.json')),
        el('table', { class: 'data' },
          el('thead', {}, el('tr', {},
            el('th', {}, 'thành phần'), el('th', {}, 'đạt'), el('th', {}, 'trọng số'), el('th', {}, ''))),
          el('tbody', {}, Object.entries(audit.by_component).map(([k, v]) => {
            const pct = (v / weights[k]) * 100;
            return el('tr', {},
              el('td', {}, k),
              el('td', {}, v.toFixed(2)),
              el('td', {}, weights[k]),
              el('td', { style: `color:${pct >= 99.5 ? 'var(--good)' : 'var(--warning)'}` }, pct.toFixed(1) + '%'));
          }))))
    );
  }
}

// ---------------------------------------------------------------------------
// architecture view
// ---------------------------------------------------------------------------
function renderArchitecture() {
  const body = $('#archBody');
  body.innerHTML = '';
  const sys = state.system;
  const scopes = Object.fromEntries((sys.agents || []).map((a) => [a.name, a.scope]));

  body.append(
    el('div', { class: 'card' },
      el('h3', {}, 'Sơ đồ agent và quyền truy cập dữ liệu'),
      buildAgentGraph(scopes),
      el('p', { style: 'margin:10px 0 0;font-size:12.5px;color:var(--ink-2)' },
        'Coordinator và Policy agent không có quyền đọc CSV. Mọi con số trong output đều đi qua '
        + 'một A2A message từ agent được phép đọc bảng tương ứng — ScopedView ném PermissionError nếu agent đọc ngoài phạm vi.'))
  );

  body.append(
    el('div', { class: 'card' },
      el('h3', {}, 'Vai trò và phạm vi'),
      el('div', { class: 'scopegrid' },
        (sys.agents || []).map((a) =>
          el('div', { class: 'scopecard' },
            el('div', { class: 'nm' }, a.name),
            el('div', { class: 'rl' }, a.role),
            el('div', { class: 'sc' },
              a.scope.length ? 'đọc: ' + a.scope.join(', ') : 'không truy cập CSDL'),
            el('div', { class: 'sc', style: 'margin-top:4px' }, 'model: ' + a.model)))))
  );

  const steps = [
    ['customer → coordinator', 'Khiếu nại tiếng Việt kèm claimed_order_id được nạp vào bus.'],
    ['coordinator: triage', 'LLM phân loại khiếu nại thành giả thuyết cần kiểm chứng — chưa kết luận gì.'],
    ['coordinator → 3 agent domain', 'Ba request song song. Mỗi agent chỉ đọc bảng thuộc phạm vi của mình.'],
    ['reconcile', 'Con số LLM đọc được đối chiếu với giá trị tính từ CSV; lệch thì lấy CSV và ghi lại vào trace.'],
    ['coordinator → policy', 'Handoff bằng chứng. Policy agent áp EC_POLICY_V1 mà không được nhìn dữ liệu gốc.'],
    ['đối chiếu hai đường', 'Kết luận LLM so với rule engine tất định. Lệch thì lấy rule engine, hạ confidence.'],
    ['coordinator → verifier', 'Kiểm tra schema, sự tồn tại của mọi ID trong CSV, số tiền, giới hạn số lượng.'],
    ['ghi file', 'output/EC_xxx.json + toàn bộ transcript vào trace.jsonl.'],
  ];
  body.append(
    el('div', { class: 'card' },
      el('h3', {}, 'Luồng xử lý một case'),
      el('div', { class: 'flowsteps' },
        steps.map(([t, d], i) =>
          el('div', { class: 'flowstep' },
            el('div', { class: 'n' }, i + 1),
            el('div', {},
              el('div', { class: 'ttl' }, t),
              el('div', { class: 'dsc' }, d))))))
  );

  const meta = sys.metadata || {};
  body.append(
    el('div', { class: 'grid2' },
      el('div', { class: 'card' },
        el('h3', {}, 'Model'),
        el('dl', { class: 'kv' },
          el('dt', {}, 'provider'), el('dd', {}, meta.models?.provider ?? '—'),
          el('dt', {}, 'model'), el('dd', { class: 'mono' }, meta.models?.default_model ?? '—'),
          el('dt', {}, 'kích thước'), el('dd', {}, `~${meta.models?.parameter_size_estimate_b ?? '—'}B / giới hạn ${meta.models?.parameter_budget_b ?? 10}B`),
          el('dt', {}, 'temperature'), el('dd', {}, String(meta.models?.temperature ?? '—')),
          el('dt', {}, 'decoding'), el('dd', {}, meta.models?.decoding ?? '—'))),
      el('div', { class: 'card' },
        el('h3', {}, 'Runtime'),
        el('dl', { class: 'kv' },
          el('dt', {}, 'framework'), el('dd', {}, meta.framework?.name ?? '—'),
          el('dt', {}, 'messaging'), el('dd', {}, meta.framework?.messaging ?? '—'),
          el('dt', {}, 'ngôn ngữ'), el('dd', {}, meta.framework?.language ?? '—'),
          el('dt', {}, 'OS'), el('dd', {}, meta.runtime?.os ?? '—'),
          el('dt', {}, 'chạy lúc'), el('dd', { class: 'mono' }, meta.generated_at ?? '—'))))
  );
}

// ---------------------------------------------------------------------------
// wiring
// ---------------------------------------------------------------------------
async function selectCase(caseId) {
  state.selected = caseId;
  renderRows();
  state.detail = await api(`/api/case/${caseId}`);
  renderDetailHead();
  renderVerdict();
  renderFlow();
  renderData();
  renderJson();
}

function switchTab(tab) {
  state.tab = tab;
  $$('#tabs button').forEach((b) => b.setAttribute('aria-current', String(b.dataset.tab === tab)));
  for (const t of ['verdict', 'flow', 'data', 'json']) $(`#pane-${t}`).hidden = t !== tab;
}

function switchView(view) {
  state.view = view;
  $$('nav.views button').forEach((b) => b.setAttribute('aria-current', String(b.dataset.view === view)));
  $$('.view').forEach((v) => v.setAttribute('data-active', String(v.dataset.view === view)));
  if (view === 'overview') renderOverview();
  if (view === 'architecture') renderArchitecture();
}

function renderTopStats() {
  const box = $('#topstats');
  box.innerHTML = '';
  const stats = state.system?.metadata?.run_stats || {};
  const audit = state.system?.audit || {};
  const usage = stats.usage || {};
  const items = [
    [int(stats.cases_run ?? state.cases.length), 'case'],
    [(audit.mean_score ?? 0).toFixed(2), 'self-audit'],
    [int(usage.calls ?? 0), 'lượt LLM'],
    ['$' + (usage.estimated_cost_usd ?? 0).toFixed(3), 'chi phí'],
    [`${((stats.policy_agreement_rate ?? 1) * 100).toFixed(0)}%`, 'đồng thuận'],
  ];
  for (const [v, k] of items) {
    box.append(el('div', { class: 'topstat' }, el('span', { class: 'v' }, v), el('span', { class: 'k' }, k)));
  }
}

async function loadCases() {
  const data = await api('/api/cases');
  state.cases = data.cases;
  renderFilters();
  renderRows();
  renderTopStats();
}

async function boot() {
  $('#search').addEventListener('input', (e) => { state.search = e.target.value; renderRows(); });
  $$('#tabs button').forEach((b) => b.addEventListener('click', () => switchTab(b.dataset.tab)));
  $$('nav.views button').forEach((b) => b.addEventListener('click', () => switchView(b.dataset.view)));
  $('#themeToggle').addEventListener('click', () => {
    const light = document.documentElement.dataset.theme === 'light';
    document.documentElement.dataset.theme = light ? 'dark' : 'light';
    $('#themeToggle').textContent = light ? 'Sáng' : 'Tối';
    if (state.view === 'overview') renderOverview();
  });

  state.system = await api('/api/system');
  await loadCases();
  if (state.cases.length) await selectCase(state.cases[0].case_id);
}

boot().catch((err) => {
  document.body.innerHTML = `<div style="padding:40px;font-family:system-ui">
    <h2>Không tải được console</h2><pre>${esc(err.message)}</pre>
    <p>Chạy <code>python -m src.run_all</code> trước để có dữ liệu, rồi <code>python -m src.server</code>.</p></div>`;
});
