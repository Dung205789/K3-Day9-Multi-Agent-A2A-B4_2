# Architecture — K3 Day09 Multi-Agent E-Commerce Dispute Resolution

## 1. Tổng quan hệ thống

Hệ thống xử lý 50 case khiếu nại thương mại điện tử trên dữ liệu Olist Brazil bằng kiến trúc **multi-agent hybrid**: mỗi agent kết hợp tính toán Python chính xác với lớp suy luận LLM (llama3.1:8b, ≤10B params, chạy local qua Ollama).

## 2. Sơ đồ kiến trúc

```
input/EC_xxx.json
        │
        ▼
┌────────────────────────────────────────────────────────────────────┐
│                       Coordinator Agent                             │
│              (Python orchestration + ThreadPoolExecutor)            │
│  1. Đọc case JSON                                                   │
│  2. Fan-out 3 agent song song                                       │
│  3. Handoff findings → Policy → Verifier                           │
│  4. Ghi output JSON + trace                                         │
└─────┬──────────────────────┬────────────────────────┬──────────────┘
      │                      │                        │
      ▼ (parallel)           ▼ (parallel)             ▼ (parallel)
┌─────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Order&Seller│    │  Payment Agent   │    │ Delivery Agent   │
│   Agent     │    │                  │    │                  │
│ ─────────── │    │ ─────────────── │    │ ──────────────── │
│ Python:     │    │ Python:          │    │ Python:          │
│  join orders│    │  sum payments    │    │  compare dates   │
│  items,sell │    │  count rows      │    │  delta_days      │
│  check limit│    │  diff ≤ 0.10BRL │    │  carrier vs limit│
│ LLM:        │    │ LLM:             │    │ LLM:             │
│  evidence ID│    │  evidence ID     │    │  finding string  │
│  finding    │    │  finding string  │    │  confidence      │
│  confidence │    │  confidence      │    │                  │
└─────┬───────┘    └──────┬───────────┘    └──────┬───────────┘
      │                   │                       │
      └───────────────────┴───────────────────────┘
                          │  3 findings (JSON)
                          ▼
             ┌────────────────────────┐
             │     Policy Agent       │
             │ ─────────────────────  │
             │ Python (deterministic):│
             │  apply EC_POLICY_V1    │
             │  rule priority table   │
             │  calc refund amount    │
             │ LLM (review only):     │
             │  confidence adjustment │
             │  edge case detection   │
             └────────────┬───────────┘
                          │  policy decision
                          ▼
             ┌────────────────────────┐
             │    Verifier Agent      │
             │ ─────────────────────  │
             │ Python:                │
             │  validate schema       │
             │  evidence ID format    │
             │  count limits          │
             │  financial amounts     │
             │ LLM (if errors only):  │
             │  generate reject_reason│
             └────────────┬───────────┘
                          │
              ┌───────────┴────────────┐
              │                        │
              ▼                        ▼
     output/EC_xxx.json      logging/trace.jsonl
```

## 3. Chi tiết từng agent

### 3.1 Coordinator Agent
- **File**: `agents/coordinator.py`
- **Model**: không dùng LLM (Python orchestration thuần)
- **Quyền truy cập data**: `input/`, `output/`, `logging/`
- **Vai trò**: điều phối toàn bộ pipeline, fan-out parallel, thu thập findings, ghi trace
- **Concurrency**: `ThreadPoolExecutor(max_workers=3)` — 3 domain agent chạy song song mỗi case

### 3.2 Order & Seller Agent
- **File**: `agents/order_seller_agent.py`
- **Model**: `llama3.1:latest` (8B params, Ollama local)
- **Quyền truy cập data**: `olist_orders_dataset.csv`, `olist_order_items_dataset.csv`
- **Python layer**: join orders → items → xác định seller nào bàn giao sau `shipping_limit_date`
- **LLM layer**: sinh evidence_id list (`order:`, `item:`, `seller:`), finding string, confidence
- **Output**: `{evidence_ids, finding, seller_late, late_seller_ids, confidence}`

### 3.3 Payment Agent
- **File**: `agents/payment_agent.py`
- **Model**: `llama3.1:latest` (8B params, Ollama local)
- **Quyền truy cập data**: `olist_order_payments_dataset.csv`, `olist_order_items_dataset.csv`
- **Python layer**: tổng payment, đếm rows, đối soát `|total_payment - (item+freight)| ≤ 0.10 BRL`
- **LLM layer**: sinh evidence_id (`payment:<order_id>:<seq>`), finding, confidence
- **Output**: `{evidence_ids, finding, has_multi_payment, payment_matches_order, confidence}`

### 3.4 Delivery Agent
- **File**: `agents/delivery_agent.py`
- **Model**: `llama3.1:latest` (8B params, Ollama local)
- **Quyền truy cập data**: `olist_orders_dataset.csv`, `olist_order_items_dataset.csv`
- **Python layer**: so sánh `order_delivered_customer_date` vs `order_estimated_delivery_date`; `order_delivered_carrier_date` vs `max(shipping_limit_date)`
- **LLM layer**: diễn giải timeline, finding string, confidence
- **Output**: `{evidence_ids, finding, is_late, carrier_received_on_time, delta_days, confidence}`

### 3.5 Policy Agent
- **File**: `agents/policy_agent.py`
- **Model**: `llama3.1:latest` (8B params, Ollama local, review only)
- **Quyền truy cập data**: nhận findings từ 3 agent (không đọc CSV trực tiếp)
- **Python layer** (authoritative): áp dụng `EC_POLICY_V1` rule table theo thứ tự ưu tiên
- **LLM layer** (advisory): review confidence, phát hiện edge case — **không override rule decision**
- **Output**: `{primary_issue, root_cause_code, case_status, resolution_actions, financial, confidence}`

### 3.6 Verifier Agent
- **File**: `agents/verifier_agent.py`
- **Model**: `llama3.1:latest` (8B params, Ollama local, conditional)
- **Quyền truy cập data**: output document từ Coordinator
- **Python layer**: validate schema, evidence ID regex, count limits, financial amounts
- **LLM layer** (chỉ khi có lỗi): sinh `reject_reason` string rõ ràng
- **Output**: `{valid, errors, reject_reason, output_doc}`

## 4. Luồng handoff

```
Case JSON
  → Coordinator reads order_id
  → [PARALLEL] Order&Seller | Payment | Delivery
      each: Python compute → LLM reason → structured JSON finding
  → Policy Agent receives 3 findings
      Python: apply rule table → deterministic decision
      LLM: review confidence only
  → Verifier Agent receives output document
      Python: validate all constraints
      LLM (if fail): generate reject_reason
  → Write output/EC_xxx.json
  → Append to logging/trace.jsonl
```

## 5. Data access per agent

| Agent | CSV files accessed |
|---|---|
| Order & Seller | `olist_orders_dataset.csv`, `olist_order_items_dataset.csv` |
| Payment | `olist_order_payments_dataset.csv`, `olist_order_items_dataset.csv` |
| Delivery | `olist_orders_dataset.csv`, `olist_order_items_dataset.csv` |
| Policy | Findings from 3 agents (no direct CSV) |
| Verifier | Output document (no CSV) |
| Coordinator | `input/`, writes to `output/`, `logging/` |

All CSV data loaded once by `agents/data_loader.py` (singleton DataStore).

## 6. Model constraint compliance

- **Model**: `llama3.1:latest` — 8B parameters ≤ 10B limit 
- **Runtime**: Ollama local (localhost:11434) 
- **Per-agent LLM calls**: 4 agents (Order&Seller, Payment, Delivery, Policy) call LLM per case 
- **Verifier**: calls LLM only when validation errors exist 

## 7. Thiết kế tránh hallucination

1. **Python facts override LLM**: Mọi số liệu tài chính và timestamp so sánh đều từ Python — LLM chỉ diễn giải, không tính toán
2. **Evidence ID validation**: Verifier kiểm tra mọi evidence ID tồn tại thực sự trong data
3. **Policy rule table**: Thứ tự ưu tiên rule cứng trong Python — LLM không thể thay đổi `primary_issue`
4. **Confidence blending**: Policy confidence = 70% Python baseline + 30% LLM review

## 8. File structure

```
K3-Day9-Multi-Agent-A2A/
├── agents/
│   ├── __init__.py
│   ├── coordinator.py          # Orchestration + fan-out
│   ├── data_loader.py          # Singleton DataStore (9 CSVs)
│   ├── delivery_agent.py       # Delivery timeline analysis
│   ├── llm_client.py           # Ollama REST wrapper
│   ├── order_seller_agent.py   # Order status + seller handoff
│   ├── payment_agent.py        # Payment reconciliation
│   ├── policy_agent.py         # EC_POLICY_V1 rule engine
│   └── verifier_agent.py       # Schema + evidence validation
├── data/                       # 9 Olist CSV files
├── input/                      # EC_001..EC_050.json
├── logging/
│   ├── metadata.json           # Model + framework info
│   └── trace.jsonl             # Per-case execution trace
├── output/                     # EC_001..EC_050.json (generated)
├── architecture.md             # This file
├── generate_inputs.py          # Input generation script
└── main.py                     # Entry point
```
