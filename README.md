# K3 Day 09 - Multi-Agent E-commerce Dispute Resolution

## 1. Bài toán

Xây dựng một hệ thống multi-agent để điều tra 50 yêu cầu hỗ trợ của khách hàng trên dữ liệu Olist. Với mỗi case, hệ thống phải đối chiếu nhiều nguồn dữ liệu, xác định vấn đề, bên chịu trách nhiệm, bằng chứng, khoản hoàn đề xuất và hành động xử lý.

Trong thực tế, một khiếu nại thương mại điện tử thường không thể được giải quyết chỉ từ nội dung khách hàng cung cấp. Nhân viên chăm sóc khách hàng phải kiểm tra trạng thái đơn, thời hạn seller bàn giao hàng, thời điểm đơn vị vận chuyển giao thực tế, các sản phẩm trong đơn và toàn bộ giao dịch thanh toán. Ví dụ, cùng một phản ánh "giao hàng trễ" nhưng trách nhiệm có thể thuộc về seller nếu bàn giao quá hạn, thuộc về đơn vị vận chuyển nếu seller đã bàn giao đúng hạn, hoặc khiếu nại có thể không chính xác nếu dữ liệu cho thấy đơn được giao đúng cam kết.

Quy trình này thường cần nhiều bộ phận phối hợp và trao đổi kết quả với nhau. Bài lab này mô phỏng quy trình đó bằng các agent: mỗi agent phân tích một domain dữ liệu, sau đó handoff bằng chứng cho agent điều phối để đưa ra kết luận cuối cùng. Hệ thống phải ưu tiên dữ liệu có thể kiểm chứng thay vì tin hoàn toàn vào lời khiếu nại hoặc tự tạo ra sự kiện không tồn tại.

## 2. Dữ liệu

https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

Thư mục `data/` chứa 9 file CSV của Brazilian E-Commerce Public Dataset by Olist. Các khóa join chính:

- `orders.customer_id -> customers.customer_id`
- `orders.order_id -> order_items.order_id`
- `orders.order_id -> order_payments.order_id`
- `orders.order_id -> order_reviews.order_id`
- `order_items.product_id -> products.product_id`
- `order_items.seller_id -> sellers.seller_id`
- Các cột `*_zip_code_prefix` có thể nối với `geolocation_zip_code_prefix` sau khi gộp geolocation theo zip code.

Lưu ý về dữ liệu:

- Mỗi `customer_id` đại diện cho một order; dùng `customer_unique_id` khi cần nhận diện cùng khách hàng qua nhiều order.
- Một order có thể có nhiều item, seller hoặc payment row.
- `payment_value` là số tiền của từng payment row, không phải giá trị của từng installment.
- Olist không có refund ledger, transaction ID, tracking checkpoint theo item hoặc bằng chứng giao sai/giao thiếu. Không cần suy diễn các sự kiện này cho đỡ tốn công.
- Các timestamp được so sánh theo giá trị trong CSV; không cần chuyển múi giờ.

## 3. Input

Thư mục `input/` có:

```text
EC_001.json
EC_002.json
...
EC_050.json
```

Với địngh chuẩn:

```json
{
  "case_id": "EC_001",
  "opened_at": "2018-10-18T00:00:00-03:00",
  "customer_request": {
    "language": "vi",
    "message": "Đơn hàng của tôi có dấu hiệu giao trễ. Hãy kiểm tra nguyên nhân và quyền lợi phù hợp.",
    "claimed_order_id": "<olist_order_id>"
  },
  "policy_version": "EC_POLICY_V1"
}
```

Gợi ý: Hệ thống dùng `claimed_order_id` để truy xuất và join các CSV.

## 4. Quy tắc nghiệp vụ

Áp dụng theo thứ tự ưu tiên dưới đây. Mọi phép tính tiền làm tròn 2 chữ số thập phân.

| Primary issue             | Điều kiện                                                                         | Responsible party                           |       Refund | Action                        |
| ------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------- | -----------: | ----------------------------- |
| `canceled_order_paid`     | `order_status = canceled` và tổng payment > 0                                     | `platform` / `OLIST_PLATFORM`               | Tổng payment | `issue_full_refund`           |
| `unavailable_order_paid`  | `order_status = unavailable` và tổng payment > 0                                  | `platform` / `OLIST_PLATFORM`               | Tổng payment | `issue_full_refund`           |
| `late_delivery_seller`    | Giao sau estimated date và carrier nhận hàng sau `shipping_limit_date`            | `seller` / seller ID vi phạm                | Tổng freight | `refund_freight`              |
| `late_delivery_logistics` | Giao sau estimated date và carrier nhận hàng không muộn hơn `shipping_limit_date` | `logistics_provider` / `LOGISTICS_PROVIDER` | Tổng freight | `refund_freight`              |
| `valid_split_payment`     | Có từ 2 payment row; tổng payment khớp tổng item + freight trong sai số 0.10 BRL  | Không có                                    |            0 | `explain_valid_split_payment` |
| `unsupported_late_claim`  | Đơn giao không muộn hơn estimated date và payment khớp                            | Không có                                    |            0 | `reject_late_refund`          |

Quy ước khi order có nhiều item: seller bị coi là bàn giao muộn nếu `order_delivered_carrier_date > shipping_limit_date` của item thuộc seller đó. Bộ 50 case chính thức không chứa tình huống mơ hồ giữa nhiều seller.

Root-cause code tương ứng:

- `SELLER_HANDOFF_AFTER_LIMIT`
- `CARRIER_DELIVERED_AFTER_ESTIMATE`
- `ORDER_CANCELED_AFTER_PAYMENT`
- `ORDER_UNAVAILABLE_AFTER_PAYMENT`
- `MULTIPLE_PAYMENTS_RECONCILED`
- `DELIVERY_WITHIN_ESTIMATE`

## 5. Evidence ID

Chỉ được nộp evidence ID có thể dựng trực tiếp từ dữ liệu:

```text
order:<order_id>
item:<order_id>:<order_item_id>
payment:<order_id>:<payment_sequential>
seller:<seller_id>
policy:<root_cause_code>
```

Ví dụ: `item:abc123:2`. Evidence không tồn tại trong CSV hoặc sai định dạng bị tính là false positive.

## 6. Output schema

Mỗi input có một output tương ứng vào `output/` (tên file khớp với input):

```json
{
  "case_id": "EC_001",
  "assessment": {
    "primary_issue": "late_delivery_seller",
    "case_status": "action_required",
    "confidence": 0.92
  },
  "affected_entities": {
    "order_ids": ["<order_id>"],
    "item_ids": ["<order_id>:1"],
    "seller_ids": ["<seller_id>"],
    "payment_ids": ["<order_id>:1"]
  },
  "root_cause_analysis": {
    "ranked_causes": [
      { "cause_code": "SELLER_HANDOFF_AFTER_LIMIT", "rank": 1 }
    ],
    "responsible_parties": [
      { "party_type": "seller", "party_id": "<seller_id>" }
    ]
  },
  "evidence_ids": [
    "order:<order_id>",
    "item:<order_id>:1",
    "payment:<order_id>:1",
    "seller:<seller_id>",
    "policy:SELLER_HANDOFF_AFTER_LIMIT"
  ],
  "financial_resolution": {
    "currency": "BRL",
    "item_total_brl": 100.0,
    "freight_total_brl": 15.0,
    "payment_total_brl": 115.0,
    "recommended_refund_brl": 15.0
  },
  "resolution_actions": ["refund_freight"]
}
```

Giới hạn: tối đa 5 ID cho mỗi entity set, 10 evidence, 3 root causes, 3 responsible parties và 5 actions. `confidence` nằm trong `[0, 1]`.

`case_status` nhận một trong hai giá trị:

- `action_required`: cần hoàn tiền.
- `no_action`: không có khoản hoàn; chỉ cần giải thích hoặc bác bỏ claim.

Nếu order không có item row, `item_ids`, `seller_ids` để rỗng và `item_total_brl`, `freight_total_brl` bằng `0.0`.

## 7. Gợi ý kiến trúc multi-agent

Đây là gợi ý, bạn thoải mái tư duy thiết kế:

- **Coordinator Agent**: nhận case, giao việc và tổng hợp output.
- **Order & Seller Agent**: kiểm tra trạng thái, item, seller và mốc bàn giao.
- **Payment Agent**: đối soát payment với item + freight.
- **Delivery Agent**: so sánh thời điểm giao thực tế với hạn giao.
- **Policy Agent**: áp dụng `EC_POLICY_V1`, kiểm tra refund và action.
- **Verifier Agent**: kiểm tra ID, số tiền và schema trước khi ghi file.

Điểm cốt lõi là nên có phân công, handoff và kiểm chứng giữa các agent; không có điểm cho việc chỉ đặt tên nhiều agent nhưng toàn bộ xử lý nằm trong một prompt duy nhất.

## 8. Nộp bài và chấm điểm

Nén folder `output/` thành file zip. Zip phải chứa đúng 50 JSON từ `EC_001.json` đến `EC_050.json`; không chứa các file lạ khác

Điểm mỗi case là tổng có trọng số:

| Thành phần                        | Trọng số |
| --------------------------------- | -------: |
| Primary issue và confidence       |      20% |
| Affected entities                 |      20% |
| Root cause và responsible parties |      15% |
| Evidence IDs                      |      15% |
| Financial resolution              |      20% |
| Resolution actions                |      10% |

Điểm cuối là trung bình của 50 case. Case bị hard gate nhận 0 điểm.

Trong repo phải có thêm:

- `architecture.md`: sơ đồ agent, vai trò, quyền truy cập và luồng handoff (đặt ở root repo)
- `individual_5SoCuoiMHV_HoVaTen.md`: báo cáo cá nhân (đặt ở root repo)
- `trace.jsonl`: trace chạy thật của 50 case (không append, chỉ cần lượt chạy mới nhất)
- `metadata.json`: model, parameter size, framework và runtime

&rarr; Làm chung trên 1 repo nhóm, báo cáo cá nhân để chung trong repo và nộp repo nhóm này, giữ nguyên tên repo không đổi

| Thời gian  | Checkpoint   | Nội dung             |
| ---------- | ------------ | -------------------- |
| 9h-9h30    | Checkpoint 1 | Công bố input đề bài |
| 9h30-12h30 | Checkpoint 2 | Competition          |
| 12h30-1h   | Checkpoint 3 | Chốt leaderboard     |

## 9. Lưu ý

1. Mỗi agent chỉ được sử dụng model dưới hoặc bằng **10B parameters**, chạy local hoặc qua provider tùy ý.
2. Khi nộp bài, chỉ nén folder `output/` thành file zip; không đưa source code, `.env` hoặc các file audit vào zip này.
3. Luôn commit toàn bộ source code lên repo trước khi nộp file output zip để chấm điểm.
4. API key và secret phải đặt trong file `.env` và không được commit. Tên model sử dụng phải được khai báo rõ trong source code, đồng thời ghi lại trong `metadata.json` (Tức là model name không ghi vào .env, cho vào code để chấm)

---

# Phần triển khai

## 10. Cách chạy

```bash
pip install -r requirements.txt
cp .env.example .env          # rồi điền OPENAI_API_KEY

python -m src.make_inputs     # sinh input/EC_001..EC_050.json (bỏ qua nếu đã có sẵn)
python -m src.run_all         # chạy 50 case -> output/ + trace.jsonl + metadata.json
python -m src.audit           # tự chấm output theo trọng số mục 8
python -m src.package_submission --prefix output   # submission.zip: output/EC_001.json …

python -m src.server          # console demo -> http://127.0.0.1:8000
```

Chạy một phần để thử nhanh:

```bash
python -m src.run_all --limit 5 --workers 3
python -m src.run_all --only EC_045          # case có bất đồng policy
```

> Tên model nằm trong `src/config.py` (`MODEL_SMALL = "gpt-4o-mini"`), không nằm
> trong `.env` — theo đúng yêu cầu mục 9.4.

## 11. Console demo

`python -m src.server` mở một giao diện vận hành gồm 3 view:

- **Hồ sơ** — 50 case, lọc theo loại kết luận. Mỗi case có 4 tab: kết luận (kèm
  bảng rule engine chỉ rõ luật nào khớp), luồng A2A (sơ đồ agent + transcript),
  dữ liệu gốc (row CSV thật đứng sau quyết định), và output JSON.
  Nút **“Chạy lại case này”** chạy pipeline thật và stream từng message A2A về
  giao diện qua SSE — node trên sơ đồ sáng lên theo message.
- **Tổng quan** — phân bố kết luận, tiền hoàn theo nhóm, phân bố confidence, chi
  phí LLM theo agent, các lần LLM đọc lệch dữ liệu bị guard chặn, và bảng tự chấm.
- **Kiến trúc** — sơ đồ agent kèm phạm vi dữ liệu từng agent, luồng 8 bước, thông
  tin model và runtime.

Giao diện không cần build step và không có dependency ngoài (`web/` chỉ có 3 file).

## 12. Kết quả trên bộ input chính thức

Chạy trên 50 case thật trong `input/` (giải nén từ `input/input.zip`):

| Chỉ số                              | Giá trị                                   |
| ----------------------------------- | ----------------------------------------- |
| Case xử lý                          | 50/50, 0 hard-gate lỗi                    |
| Tự chấm (`src/audit.py`)            | **100.00 / 100** (cả 6 hạng mục tối đa)   |
| Thời gian                           | 100,6 giây (8 worker), ~2,0 s/case         |
| Lượt gọi LLM                        | 350 (7 lượt/case), 300.654 token, ~$0.065 |
| Message A2A ghi vào `trace.jsonl`   | 651                                       |
| Policy agent đồng thuận rule engine | 98% (1 bất đồng: `EC_042`)                |
| LLM đọc lệch dữ liệu                | 67 field (40 critical) — guard chặn hết   |
| Tổng hoàn đề xuất                   | 3.429,64 BRL                              |

Phân bố kết luận khớp đúng đáp án dựng từ CSV: `valid_split_payment` 9,
`unsupported_late_claim` 9, `canceled_order_paid` 8, `late_delivery_seller` 8,
`unavailable_order_paid` 8, `late_delivery_logistics` 8.

Trong bộ chính thức có **8 case không có item row** (`EC_005`, `EC_011`,
`EC_013`, `EC_019`, `EC_024`, `EC_027`, `EC_028`, `EC_036`) — ca biên mục 6 nêu
riêng. Cả 8 đều ra `item_ids`/`seller_ids` rỗng và `item_total_brl`/
`freight_total_brl` bằng `0.0`, không case nào dính hard gate.

`src/audit.py` là bộ tự chấm của repo này, dựng lại đáp án đúng trực tiếp từ CSV
rồi so với `output/` theo đúng trọng số mục 8. Nó không phải bộ chấm chính thức,
nhưng một case đạt 100 ở đây là case mà mọi field khớp với dữ liệu.

## 13. Ghi chú về `input/`

`input/` chứa 50 case chính thức, giải nén từ `input/input.zip`. Pipeline đọc
thẳng mọi file `EC_*.json` có trong thư mục.

`src/make_inputs.py` là công cụ dự phòng dùng hồi repo chưa có bộ input: nó chọn
order thật từ Olist phủ đủ 6 nhánh EC_POLICY_V1 và sinh khiếu nại tiếng Việt
theo góc nhìn khách hàng. Không còn cần cho việc nộp bài, nhưng vẫn hữu ích để
sinh thêm ca kiểm thử — nhất là các nhánh mà bộ chính thức không chạm tới.
