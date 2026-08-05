# Tóm Tắt Cốt Lõi: K3 Day 09 - Multi-Agent E-commerce Dispute Resolution

Tài liệu này tóm tắt những trọng tâm cốt lõi, quy tắc nghiệp vụ quan trọng nhất và các "bẫy" kỹ thuật cần nắm vững để thiết kế và triển khai thành công hệ thống Multi-Agent cho bài toán giải quyết khiếu nại đơn hàng Olist.

---

## 1. Bản Chất Bài Toán & Triết Lý Thiết Kế

- **Mục tiêu:** Xây dựng hệ thống **Multi-Agent** tự động phân tích và giải quyết 50 ca khiếu nại thương mại điện tử (bộ dữ liệu Olist) trong thư mục `input/` (`EC_001.json` -> `EC_050.json`), xuất kết quả ra thư mục `output/`.
- **Triết lý cốt lõi (Verifiable Truth):** Lời khiếu nại của khách hàng có thể sai hoặc thiếu chính xác. Hệ thống **tuyệt đối không tin tưởng hoàn toàn vào lời claim**, cũng **không được tự suy diễn/bịa đặt sự kiện** (như giao sai, giao thiếu, hay tự chế ID). Mọi kết luận đều phải dựa trên bằng chứng kiểm chứng được từ CSV.

---

## 2. Quy Tắc Nghiệp Vụ & Bảng Quyết Định (Chính Sách V1)

> [!IMPORTANT]
> **Thứ tự ưu tiên mang tính quyết định:** Phải kiểm tra và áp dụng các quy tắc **đúng theo thứ tự từ trên xuống dưới** trong bảng dưới đây.

| Thứ tự | Primary Issue | Điều kiện kích hoạt | Responsible Party | Root Cause Code | Khoản Hoàn (Refund) | Action | Case Status |
| :---: | :--- | :--- | :--- | :--- | :---: | :--- | :---: |
| **1** | `canceled_order_paid` | `order_status = canceled` **VÀ** Tổng payment > 0 | `platform` / `OLIST_PLATFORM` | `ORDER_CANCELED_AFTER_PAYMENT` | Tổng payment | `issue_full_refund` | `action_required` |
| **2** | `unavailable_order_paid` | `order_status = unavailable` **VÀ** Tổng payment > 0 | `platform` / `OLIST_PLATFORM` | `ORDER_UNAVAILABLE_AFTER_PAYMENT` | Tổng payment | `issue_full_refund` | `action_required` |
| **3** | `late_delivery_seller` | Giao trễ hơn estimate **VÀ** Carrier nhận hàng **sau** `shipping_limit_date` | `seller` / *(ID seller vi phạm)* | `SELLER_HANDOFF_AFTER_LIMIT` | Tổng freight | `refund_freight` | `action_required` |
| **4** | `late_delivery_logistics` | Giao trễ hơn estimate **VÀ** Carrier nhận hàng **không muộn hơn** `shipping_limit_date` | `logistics_provider` / `LOGISTICS_PROVIDER` | `CARRIER_DELIVERED_AFTER_ESTIMATE` | Tổng freight | `refund_freight` | `action_required` |
| **5** | `valid_split_payment` | Có $\ge$ 2 payment rows; Tổng payment khớp (item + freight) trong sai số **0.10 BRL** | *Không có* | `MULTIPLE_PAYMENTS_RECONCILED` | 0 | `explain_valid_split_payment` | `no_action` |
| **6** | `unsupported_late_claim` | Đơn giao **không muộn hơn** estimated date **VÀ** payment khớp | *Không có* | `DELIVERY_WITHIN_ESTIMATE` | 0 | `reject_late_refund` | `no_action` |

### Các Quy Ước Tính Toán & Phân Khởi
- **Làm tròn số:** Mọi phép tính tiền tệ (BRL) đều phải **làm tròn 2 chữ số thập phân** (ví dụ: `100.0`, `15.50`).
- **Nhiều seller trong 1 đơn:** Seller bị coi là giao muộn nếu `order_delivered_carrier_date > shipping_limit_date` của item thuộc seller đó *(bộ 50 case chính thức không có tình huống mơ hồ giữa nhiều seller)*.
- **Trạng thái xử lý (`case_status`):**
  - `action_required`: Khi cần chi tiền hoàn (Refund > 0).
  - `no_action`: Khi Refund = 0 (chỉ giải thích hoặc từ chối khiếu nại).
- **Trường hợp đơn không có Item Row:** Để rỗng `item_ids`, `seller_ids` và gán `item_total_brl = 0.0`, `freight_total_brl = 0.0`.

---

## 3. Đặc Điểm Dữ Liệu Olist & Các "Bẫy" Cần Lưu Ý

> [!WARNING]
> **Không suy diễn dữ liệu ngoài CSV:** Olist không có refund ledger, transaction ID, tracking checkpoint theo từng item, hay chứng cứ giao sai/thiếu. Đừng viết prompt hay code bắt agent đi tìm các thông tin vô hình này!

1. **Định danh khách hàng (Customer vs. Order):** 
   - Cột `customer_id` trong bảng `orders` là **mỗi order một ID riêng**. Khi cần kết nối một khách hàng qua nhiều đơn hàng khác nhau, phải dùng `customer_unique_id`.
2. **Payment Value:** Cột `payment_value` trong `order_payments` là giá trị của **từng dòng giao dịch (payment row)**, KHÔNG PHẢI giá trị của từng kỳ trả góp (installment).
3. **So sánh Timestamp:** So sánh trực tiếp theo giá trị chuỗi (string/ISO timestamp) có sẵn trong file CSV; **tuyệt đối không cần/không được chuyển múi giờ (timezone)**.

---

## 4. Định Dạng Evidence ID (Bằng Chứng)

Mọi Evidence ID nộp trong output phải được dựng hợp lệ từ dữ liệu thực tế:
- `order:<order_id>`
- `item:<order_id>:<order_item_id>`
- `payment:<order_id>:<payment_sequential>`
- `seller:<seller_id>`
- `policy:<root_cause_code>` *(ví dụ: `policy:SELLER_HANDOFF_AFTER_LIMIT`)*

> [!CAUTION]
> **Nguy cơ 0 điểm (Hard Gate):** Bất kỳ Evidence ID nào không tồn tại trong CSV hoặc sai định dạng đều bị chấm là **False Positive**. Case vi phạm hard gate sẽ bị **0 điểm**.

---

## 5. Giới Hạn & Ràng Buộc Schema Output

Output JSON (đặt ở folder `output/` với tên file từ `EC_001.json` đến `EC_050.json`) tuân thủ nghiêm ngặt các giới hạn kích thước mảng:
- `affected_entities`: Tối đa **5 ID** cho mỗi entity set (`order_ids`, `item_ids`, `seller_ids`, `payment_ids`).
- `evidence_ids`: Tối đa **10 evidence**.
- `root_cause_analysis.ranked_causes`: Tối đa **3 root causes**.
- `root_cause_analysis.responsible_parties`: Tối đa **3 responsible parties**.
- `resolution_actions`: Tối đa **5 actions**.
- `confidence`: Giá trị float nằm trong khoảng `[0, 1]`.

---

## 6. Yêu Cầu Về Kiến Trúc Multi-Agent & Kỹ Thuật

> [!CAUTION]
> **Quy tắc phân chia Agent:** Phải có sự phân công (specialization), handoff thông tin và kiểm chứng lẫn nhau thực sự. Việc gộp toàn bộ logic vào 1 prompt khổng lồ rồi "nhận vơ" là multi-agent sẽ **không được công nhận / 0 điểm**.

### Gợi ý Mô Hình Đội Ngũ Agent
1. **Coordinator Agent:** Điều phối luồng xử lý, tiếp nhận case từ khách hàng và tổng hợp ra output JSON cuối cùng.
2. **Order & Seller Agent:** Chuyên trách điều tra thông tin đơn hàng, danh sách item, seller và các mốc hạn bàn giao (`shipping_limit_date`).
3. **Payment Agent:** Chuyên trách đối soát tài chính, cộng dồn payment và kiểm tra chênh lệch với tổng (item + freight).
4. **Delivery Agent:** Chuyên trách mốc thời gian giao hàng thực tế vs. ngày cam kết (`estimated_delivery_date`, `delivered_carrier_date`, `delivered_customer_date`).
5. **Policy Agent:** Chuyên gia thẩm định chính sách, đối chiếu kết quả điều tra vào Bảng Quy Tắc V1 để chốt lỗi, người chịu trách nhiệm và khoản hoàn.
6. **Verifier / Critic Agent (Cực kỳ quan trọng):** Kiểm tra lỗi logic, xác thực 100% Evidence ID phải có trong data, validate schema trước khi ghi file JSON.

### Ràng Buộc Kỹ Thuật (Chấm Điểm)
- **Model Parameter $\le$ 10B:** Mỗi agent chỉ được dùng model LLM có số lượng tham số **dưới hoặc bằng 10B** (có thể chạy local hoặc qua Cloud Provider).
- **Khai báo Model:** Tên model sử dụng **phải khai báo trực tiếp trong source code** và ghi vào `metadata.json` *(tuyệt đối không giấu tên model trong `.env`)*.
- **Bảo mật:** API Key/Secrets phải đặt trong `.env`, không được commit.

---

## 7. Các File Bắt buộc Phải Nộp

Khi hoàn thành, repo và file nộp bài phải đảm bảo:
1. **Thư mục Nộp Bài (Zip File):** Chỉ nén duy nhất folder `output/` (chứa đúng 50 file `EC_001.json` -> `EC_050.json`). KHÔNG chứa source code, file lạ hay `.env` trong file zip nộp chấm điểm.
2. **Các File Bắt Buộc Ở Root Repo (Commit trước khi nộp zip):**
   - `architecture.md`: Sơ đồ kiến trúc multi-agent, vai trò, quyền truy cập dữ liệu và luồng handoff.
   - `trace.jsonl`: File log trace lượt chạy thật thành công mới nhất của 50 case *(ghi đè/tạo mới hoàn toàn, không append log cũ)*.
   - `metadata.json`: Ghi chi tiết model name, parameter size ($\le$ 10B), framework và runtime sử dụng.
