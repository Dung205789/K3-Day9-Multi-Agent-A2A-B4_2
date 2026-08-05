# Kiến trúc hệ thống multi-agent xử lý khiếu nại Olist

Hệ thống mô phỏng một tổ chăm sóc khách hàng: mỗi agent phụ trách một domain dữ
liệu, bàn giao bằng chứng qua message A2A, và một agent kiểm chứng chặn đầu ra
trước khi ghi file.

## 1. Sơ đồ agent

```
                                  ┌──────────────────────┐
                             ┌───▶│    order_seller      │
                             │    │ orders, order_items, │
                             │    │ sellers, products    │
                             │    └──────────┬───────────┘
                             │               │
 ┌──────────┐   ┌────────────┴───┐  ┌────────▼─────────┐   ┌──────────────┐
 │ customer │──▶│  coordinator   │─▶│     payment      │   │    policy    │
 │ khiếu nại│   │ KHÔNG đọc CSDL │  │ order_payments,  │   │ EC_POLICY_V1 │
 └──────────┘   └────────┬───────┘  │ order_items      │   │ KHÔNG đọc    │
                         │          └────────┬─────────┘   │ CSDL         │
                         │                   │             └──────┬───────┘
                         │    ┌──────────────▼──────┐             │
                         └───▶│      delivery       │             │
                              │ orders, order_items │             │
                              └─────────────────────┘             │
                                                                  │
                         ┌────────────────────────────────────────┘
                         ▼
                 ┌───────────────┐
                 │   verifier    │  chỉ được hỏi "ID này có tồn tại không",
                 │  hard gates   │  không đọc nội dung row
                 └───────┬───────┘
                         ▼
                output/EC_xxx.json
```

Toàn bộ 7 mũi tên đều là message A2A có ghi log. Không có kênh phụ nào: nếu một
con số xuất hiện trong output, nó đã đi qua một message từ agent được phép đọc
bảng chứa con số đó.

## 2. Vai trò và quyền truy cập

| Agent          | Vai trò                                                       | Bảng được đọc                                | Model       |
| -------------- | ------------------------------------------------------------- | -------------------------------------------- | ----------- |
| `coordinator`  | Phân loại khiếu nại, giao việc, tổng hợp, chốt confidence     | **không có**                                 | gpt-4o-mini |
| `order_seller` | Trạng thái đơn, danh sách item/seller, mốc bàn giao carrier    | `orders`, `order_items`, `sellers`, `products` | gpt-4o-mini |
| `payment`      | Đối soát tổng payment với item + freight, phát hiện split      | `order_payments`, `order_items`              | gpt-4o-mini |
| `delivery`     | So sánh thời điểm giao thực tế với hạn cam kết                 | `orders`, `order_items`                      | gpt-4o-mini |
| `policy`       | Áp EC_POLICY_V1 lên bằng chứng đã handoff                      | **không có**                                 | gpt-4o-mini |
| `verifier`     | Schema, sự tồn tại của ID, số tiền, giới hạn số lượng          | chỉ kiểm tra tồn tại ID                      | gpt-4o-mini |

Phạm vi được cưỡng chế bằng code, không phải bằng quy ước. `ScopedView`
(`src/datastore.py`) ném `PermissionError` nếu một agent gọi bảng ngoài phạm vi:

```python
AGENT_SCOPES = {
    "coordinator": (),
    "order_seller": ("orders", "order_items", "sellers", "products"),
    "payment": ("order_payments", "order_items"),
    "delivery": ("orders", "order_items"),
    "policy": (),
    "verifier": ("__existence__",),
}
```

Đây là lý do các handoff có ý nghĩa thật: Payment agent **không thể** tự xem mốc
giao hàng để kết luận đơn có trễ hay không — nó buộc phải để Delivery agent trả
lời phần đó.

## 3. Giao thức A2A

Mỗi message là một envelope JSON ghi vào `trace.jsonl`:

```json
{
  "case_id": "EC_002",
  "msg_id": "3f9c1a7b2d04",
  "reply_to": "a1b2c3d4e5f6",
  "ts": "2026-08-04T16:27:02.063+00:00",
  "sender": "order_seller",
  "recipient": "coordinator",
  "performative": "inform",
  "intent": "order_seller_findings",
  "payload": { "...": "..." },
  "meta": { "latency_ms": 1955, "prompt_tokens": 482, "tables_read": ["orders", "order_items"] }
}
```

Bộ performative theo phong cách FIPA:

| Performative | Ý nghĩa                                              |
| ------------ | ---------------------------------------------------- |
| `request`    | coordinator giao việc điều tra cho agent domain      |
| `inform`     | agent trả kết quả điều tra                           |
| `handoff`    | bàn giao quyền xử lý kèm toàn bộ ngữ cảnh            |
| `query`      | hỏi một dữ kiện nằm ngoài phạm vi của mình           |
| `confirm`    | verifier thông qua bản nháp                          |
| `reject`     | verifier chặn, hoặc coordinator ghi nhận bất đồng    |
| `escalate`   | agent không thể quyết định (vd order_id không tồn tại) |

## 4. Luồng xử lý một case

1. **`customer → coordinator`** (`request/open_case`) — nạp khiếu nại tiếng Việt
   kèm `claimed_order_id`.
2. **Coordinator triage** — LLM đọc lời khiếu nại và biến nó thành *giả thuyết
   cần kiểm chứng*, không phải kết luận. Lời khách nói có thể sai.
3. **`coordinator → 3 agent domain`** (`request/investigate`, song song) — mỗi
   agent nhận raw row trong phạm vi của mình và tự rút ra kết luận domain.
4. **Lớp reconcile** — mỗi con số LLM đọc được được đối chiếu với giá trị tính
   trực tiếp từ CSV. Lệch thì lấy giá trị CSV và ghi lại bất thường vào trace,
   kèm mức độ (`critical` nếu ảnh hưởng tới nhánh policy, `minor` nếu chỉ là làm
   tròn). Đây là cơ chế chính giữ độ chính xác khi dùng model nhỏ.
5. **`coordinator → policy`** (`handoff/apply_policy`) — Policy agent áp
   EC_POLICY_V1 chỉ dựa trên bằng chứng nhận được, không được nhìn dữ liệu gốc.
6. **Đối chiếu hai đường quyết định độc lập** — kết luận của Policy agent (LLM)
   so với `src/policy.py` (rule engine tất định). Khi lệch, hệ thống lấy rule
   engine, phát message `reject/policy_disagreement` và hạ confidence của case.
7. **`coordinator → verifier`** (`handoff/verify_draft`) — hai lượt kiểm tra:
   - *tất định*: schema, enum, giới hạn số lượng, cú pháp evidence ID, **sự tồn
     tại thật của mọi ID trong CSV**, số tiền hoàn đúng loại theo issue, tính
     nhất quán giữa `case_status` và refund. Lớp này được phép sửa bản nháp.
   - *LLM*: rà soát ngữ nghĩa, mỗi check phải trích được `field=giá trị` cụ thể.
     Fail không trích được bằng chứng bị hạ xuống `pass`; fail trên phần mà lớp
     tất định đã chứng minh bằng số bị hạ xuống `advisory` — một tín hiệu yếu
     không được lật một chứng minh.
8. **Ghi file** — `output/EC_xxx.json` + toàn bộ transcript vào `trace.jsonl`.

## 5. Vì sao có cả LLM lẫn rule engine

Đề bài yêu cầu model ≤ 10B. Model nhỏ đọc bảng luật tốt nhưng cộng số và so sánh
timestamp không ổn định. Thiết kế ở đây tách hai việc đó:

- **LLM làm phần phán đoán**: đọc lời khiếu nại, diễn giải bằng chứng, viết lập
  luận, rà soát ngữ nghĩa.
- **Code làm phần số học và so sánh**: tổng tiền, so sánh mốc thời gian, dựng
  evidence ID, kiểm tra tồn tại.

Và quan trọng: hệ thống **đo** mức lệch giữa hai bên thay vì giấu đi. Trên bộ 50
case chính thức, LLM đọc sai 67 field (40 field ảnh hưởng tới nhánh policy) —
tất cả đều bị lớp reconcile ghi đè, và có 1 case Policy agent kết luận khác rule
engine (`EC_042`). Những con số này hiển thị trực tiếp trên console và nằm trong
`metadata.json`.

## 6. Confidence được tính thế nào

Không phải số do LLM tự bịa. Bắt đầu từ 0.95 rồi trừ đi theo tín hiệu thật:

| Tín hiệu                                        | Ảnh hưởng          |
| ----------------------------------------------- | ------------------ |
| Policy agent bất đồng với rule engine           | −0.15              |
| Verifier LLM không thông qua                    | −0.08, cộng adj    |
| Mỗi lần verifier phải sửa bản nháp              | −0.02 (tối đa 4)   |
| Mỗi field LLM đọc lệch dữ liệu ở mức `critical` | −0.03 (tối đa 3)   |

Kết quả nằm trong `[0.35, 0.99]`. Case sạch được ~0.95; case có bất đồng tụt
xuống ~0.71 — đúng thứ mà một reviewer cần nhìn để biết hồ sơ nào phải xem lại.

## 7. Bản đồ mã nguồn

```
src/
  config.py        hằng số, tên model (ĐỂ Ở ĐÂY, không để trong .env)
  datastore.py     nạp 9 CSV, index theo order_id, ScopedView cưỡng chế phạm vi
  policy.py        EC_POLICY_V1 dạng code - rule engine tất định + dựng evidence
  a2a.py           envelope, bus, TraceRecorder (ghi trace.jsonl)
  llm.py           wrapper OpenAI: JSON mode, retry, đếm token/chi phí
  agents/
    base.py          lớp Agent, hàm reconcile (guard số học)
    coordinator.py   triage, fan-out song song, tổng hợp
    order_seller.py  order_seller agent
    payment.py       payment agent
    delivery.py      delivery agent
    policy_agent.py  policy agent (LLM)
    verifier.py      verifier agent (tất định + LLM)
  pipeline.py      chạy một case end-to-end
  run_all.py       chạy toàn bộ input/ -> output/ + trace + metadata
  audit.py         tự chấm output theo trọng số đề bài
  make_inputs.py   sinh 50 case input từ dữ liệu Olist
  server.py        backend Starlette cho console demo
web/               console demo (không build step, không dependency)
```
