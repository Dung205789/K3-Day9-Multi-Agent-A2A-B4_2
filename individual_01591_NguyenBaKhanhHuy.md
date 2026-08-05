# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung                          |
| -----------------| -----------------------------------|
| Họ và tên       | Nguyễn Bá Khánh Huy               |
| MSSV            | 01591                             |
| Khóa/Lớp        | K3                                |
| Vai trò chính   | Multi-Agent Architect & Developer |
| Ngày hoàn thành | 2026-08-05                        |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable                   | File/hàm phụ trách                                                                                              | Input nhận vào          | Output bàn giao                                          | Trạng thái |
| --------------------------------------| -----------------------------------------------------------------------------------------------------------------| -------------------------| ----------------------------------------------------------| ------------|
| Multi-Agent Orchestration & Pipeline | `agents/coordinator.py`, `main.py`                                                                              | Case JSON từ `input/`   | `output/EC_xxx.json`, `logging/trace.jsonl`              | Hoàn thành |
| Domain Agents & Business Rules       | `agents/order_seller_agent.py`, `agents/payment_agent.py`, `agents/delivery_agent.py`, `agents/policy_agent.py` | CSV Datasets & Case ID  | Structured JSON Findings & Policy Decision               | Hoàn thành |
| Validation Guardrails & LLM Client   | `agents/verifier_agent.py`, `agents/llm_client.py`                                                              | Output Doc & Ollama API | Cleaned JSON, Reject Reason, Metadata                    | Hoàn thành |
| Data Loading & Input Benchmark       | `agents/data_loader.py`, `generate_inputs.py`                                                                   | 9 file CSV Olist        | Singleton DataStore & 50 Input Cases (`EC_001`-`EC_050`) | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                       | Thành viên/module được hỗ trợ | Kết quả                                                 |
| ---------------------------------| -------------------------------| ---------------------------------------------------------|
| Đóng gói và kiểm thử End-to-End | Entire Project / `output.zip` | 50/50 case pass 100% validation, nén thành `output.zip` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --------------------- | --------------------------- | ------------------------- | --------------- |
| Xây dựng Orchestration & Parallel Fan-out | `agents/coordinator.py` | Fan-out song song 3 domain agents qua `ThreadPoolExecutor` | `python3 main.py` |
| Cấu hình Rule Engine `EC_POLICY_V1` | `agents/policy_agent.py` | Áp dụng đúng thứ tự ưu tiên 6 kịch bản quy tắc | Đo sánh đối soát với `input/` ground-truth |
| Kiểm chứng bằng chứng & Regex ID | `agents/verifier_agent.py` | 100% evidence_ids đúng định dạng, không vi phạm limit | Verifier Agent validation |
| Chạy benchmark toàn bộ 50 case | `main.py`, `output/` | 50 file JSON hợp lệ trong `output/` | `zip -r output.zip output/` |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

Đã tạo ra toàn bộ 50 file output JSON trong thư mục `output/` (`EC_001.json` đến `EC_050.json`), vượt qua 100% các bài kiểm tra validation của Verifier Agent mà không có bất kỳ lỗi schema hay sai định dạng Evidence ID nào. File nộp bài đã được đóng gói thành `output.zip`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Hệ thống cần tự động điều tra và giải quyết 50 khiếu nại thương mại điện tử phức tạp dựa trên dữ liệu Olist Brazil. Thách thức lớn nhất là tránh LLM Hallucination đối với các mốc thời gian, số tiền thanh toán và định dạng Evidence ID, đồng thời phải đảm bảo thời gian xử lý nhanh và tuân thủ ràng buộc chỉ dùng model $\le 10\text{B}$ parameters (`llama3.1:8b` qua Ollama local).

### Cách triển khai

Hệ thống được thiết kế theo kiến trúc **Multi-Agent Hybrid (Python Precision + LLM Reasoning)**:
1. **Lớp Python (Authoritative Ground Truth)**: Đảm nhận toàn bộ các phép tính số học chính xác (tổng tiền thanh toán, tổng giá trị sản phẩm + phí vận chuyển, khoảng cách ngày giao hàng) và áp dụng bảng quy tắc cứng `EC_POLICY_V1` theo đúng thứ tự ưu tiên.
2. **Lớp LLM (`llama3.1:8b`)**: Chỉ đảm nhận diễn giải ngữ nghĩa (`finding`), gợi ý danh sách `evidence_ids` và đánh giá độ tin cậy (`confidence`).
3. **Orchestration**: `Coordinator Agent` dùng `ThreadPoolExecutor(max_workers=3)` để chạy song song 3 domain agent (`OrderSeller`, `Payment`, `Delivery`), sau đó handoff kết quả tới `Policy Agent` và `Verifier Agent`.

### Input, output và contract

| Thành phần | Mô tả |
| ----------------------- | -------------------------------------- |
| Input | File `input/EC_xxx.json` chứa `case_id`, `claimed_order_id`, `opened_at`, `customer_request`. |
| Output | File `output/EC_xxx.json` tuân thủ đúng Output Schema (`assessment`, `affected_entities`, `root_cause_analysis`, `evidence_ids`, `financial_resolution`, `resolution_actions`). |
| Module phụ thuộc | `agents/data_loader.py` (Singleton DataStore 9 CSVs). |
| Module sử dụng output | `agents/verifier_agent.py` và Hệ thống chấm điểm tự động. |
| Điều kiện lỗi cần xử lý | Order không có item row, timestamp bị null/NaT, LLM trả về JSON lỗi format, LLM timeout. |

### Cách xác minh

```bash
python3 main.py
```

- **Kết quả mong đợi:** 50/50 case xử lý thành công, 0 lỗi, thời gian chạy tối ưu, đủ 50 file `EC_001.json` -> `EC_050.json`.
- **Kết quả thực tế:** 50 success, 0 error trong 134.5s; Verifier Agent xác nhận valid 100%.
- **Artifact/log:** `output.zip`, `logging/trace.jsonl`, `logging/metadata.json`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Lựa chọn phương pháp áp dụng quy tắc nghiệp vụ `EC_POLICY_V1` cho hệ thống Multi-Agent.
- **Các phương án đã cân nhắc:**
  1. *Phương án A*: Đưa toàn bộ quy tắc vào Prompt và để LLM 8B tự suy luận ra `primary_issue`, bên chịu trách nhiệm và số tiền hoàn.
  2. *Phương án B*: Sử dụng hàm Python thuần (`_apply_rules`) để quyết định `primary_issue` và tính toán số tiền hoàn dựa trên facts từ CSV, sau đó cho LLM review confidence.
- **Phương án đã chọn:** Phương án B (Python Authoritative Rule Engine + LLM Review).
- **Lý do:** Các mô hình LLM nhỏ ($\le 10\text{B}$) khi chạy local dễ bị nhầm lẫn khi so sánh logic điều kiện phức tạp (ví dụ: so sánh mốc `carrier_delivered_date` vs `shipping_limit_date`). Dùng Python làm Authoritative loại bỏ 100% rủi ro hallucination, đảm bảo kết quả chính xác tuyệt đối.
- **Bằng chứng quyết định phù hợp:** 50/50 case khi kiểm thử đều đạt 0 lỗi validation và khớp 100% logic với bộ quy tắc `EC_POLICY_V1`.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Case `EC_005` bị rỗng danh sách `item_ids` và `seller_ids`, dẫn đến nguy cơ sinh ra output vi phạm schema hoặc tính sai tổng tiền.
- **Lệnh hoặc bước tái hiện:** `python3 main.py EC_005`
- **Nguyên nhân gốc:** Đơn hàng `ea844c92cf978ea23321fa7fe5871761` trong Olist dataset có thông tin thanh toán (`414.04 BRL`) nhưng không chứa dòng sản phẩm nào trong file `olist_order_items_dataset.csv`.
- **Cách xử lý:** Cập nhật logic trong `agents/order_seller_agent.py` và `agents/coordinator.py` để xử lý an toàn trường hợp order không có item row: gán `item_ids: []`, `seller_ids: []`, `item_total_brl: 0.0`, `freight_total_brl: 0.0` và hoàn trả đúng `payment_total_brl` theo đúng chỉ dẫn tại Mục 6 của `README.md`.
- **Cách xác minh sau khi sửa:** Chạy `python3 main.py EC_005`, file `output/EC_005.json` được tạo thành công với `valid: True`.
- **Điều học được:** Khi làm việc với dữ liệu thực tế (real-world datasets), luôn phải triển khai lập trình phòng vệ (defensive programming) cho các trường hợp quan hệ dữ liệu 1-N bị trống.

## 7. Hiểu biết về luồng end-to-end

Giải thích ngắn gọn bằng lời của bạn:

1. **Dữ liệu đi trong pipeline như thế nào?**
   Dữ liệu từ 9 file CSV Olist được `DataStore` singleton load vào bộ nhớ. Khi nhận một `case_id`, `Coordinator` lấy `claimed_order_id` và kích hoạt song song 3 domain agent (`OrderSeller`, `Payment`, `Delivery`). Các agent này trích xuất số liệu bằng Python và dùng LLM sinh finding. Tiếp theo, `Policy Agent` tổng hợp các finding để đưa ra quyết định hoàn tiền theo rule `EC_POLICY_V1`. Cuối cùng, `Verifier Agent` kiểm tra toàn bộ định dạng và schema trước khi xuất file `output/EC_xxx.json`.

2. **Evaluation set và ground-truth dùng để làm gì?**
   Bộ 50 case input (`EC_001` - `EC_050`) đóng vai trò là evaluation set. Mỗi case chứa câu khiếu nại thực tế của khách hàng và ground-truth tương ứng với 6 loại kịch bản nghiệp vụ. Bộ dữ liệu này dùng để đánh giá độ chính xác của hệ thống qua các chỉ số: `primary_issue`, `affected_entities`, `root_cause_analysis`, `evidence_ids` và `financial_resolution`.

3. **Quality checks khác freshness monitoring ở điểm nào?**
   - *Quality checks* (được đảm nhận bởi `Verifier Agent`): Kiểm tra tính đúng đắn về mặt định dạng, ranh giới dữ liệu (limit), regex của Evidence ID và tính toàn vẹn của kết quả ngay tại thời điểm runtime trước khi xuất file.
   - *Freshness monitoring*: Kiểm tra mức độ cập nhật và tính mới của dữ liệu nguồn (CSVs / database) theo thời gian để đảm bảo không bị dùng dữ liệu quá hạn.

4. **Vì sao phải dùng cùng test set cho baseline, corrupted và repaired?**
   Việc giữ nguyên cùng một test set 50 case cho phép so sánh trực quan, công bằng và chính xác các chỉ số hiệu năng (accuracy, precision, validation pass rate) giữa các phiên bản hệ thống, từ đó đo lường được mức độ cải thiện của kiến trúc multi-agent so với baseline.

5. **Xử lý case (Resolution/Repair) được xem là thành công dựa trên artifact và metric nào?**
   Xử lý case được xem là thành công khi:
   - File `output/EC_xxx.json` được khởi tạo thành công và vượt qua 100% bài kiểm tra của `Verifier Agent` (0 lỗi validation).
   - `primary_issue` và `recommended_refund_brl` khớp tuyệt đối với quy tắc `EC_POLICY_V1`.
   - Tất cả `evidence_ids` đều tồn tại thực tế và đúng cú pháp regex.
   - Trace lịch sử chạy được ghi nhận đầy đủ trong `logging/trace.jsonl`.

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Bá Khánh Huy  
**Ngày xác nhận:** 2026-08-05
